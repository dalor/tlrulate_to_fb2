import re
import asyncio
import aiohttp
from io import BytesIO
from PIL import Image
import base64
from fb2book import FB2book

parse_page_info = re.compile(r'\<h1\>(?P<title>.+)\<\/h1\>\n\<div\sid\=\'Info\'[\s\S]+\<img\ssrc\=\"(?P<img>\/i\/book\/[a-z0-9\/\.]+)\"[\s\S]+(?P<description>\<p\>\<strong\>Автор\:\<\/strong\>\s\<em\>\<a\shref\=.+)\n')

parse_chapters = re.compile(r'\<tr\sid\=\'(c\_|vol\_title\_)(?P<index>[0-9]+)\'[^>]*class\=\'(?P<type>chapter\_row|volume_helper)\s*(?P<volume_to>[^\' ]*)\s?\'\>\<td(\scolspan\=\'14\'\sonclick\=\'\$\(\".(?P<volume>volume\_[0-9a-z]+)\"\)[^<]+\<strong\>(?P<title>[^<]+)|\>\<\/td\>\<td\sclass\=\'t\'\>\<a\shref\=\'(?P<url>[^\']+)\'\>(?P<name>[^<]+)\<\/a\>)')

parse_chapter_content = re.compile(r'\<div\sid\=\"readpage\"\>([\S\s]+)\<\/div\>\n\<div\sstyle\=\"text\-align\:\scenter\;\smargin\-bottom\:\s20px\;\"')

img_pattern = re.compile(r'\<img\ssrc\=\"([^\"]+)\"\s*\/\>')

class Picture:
    def __init__(self, name, type_, content):
        self.name = name
        self.type = type_
        self.content = content

class Row:
    def __init__(self, result, index=0):
        self.is_chapter = result['type'] == 'chapter_row'
        self.url = result['url'] if self.is_chapter else None
        self.name = result['name'] if self.is_chapter else result['title']
        self.index = index
        self.volume = result['volume'] if not self.is_chapter else None
        self.volume_to = result['volume_to'] if self.is_chapter else None

    def __repr__(self):
        return '{} № {}\nName: {}\nUrl: {}\nVolume_to: {}\nVolume: {}'.format(
            'Chapter' if self.is_chapter else 'Volume', self.index, self.name, self.url, self.volume_to, self.volume)

class Chapter:
    def __init__(self, name, content=None, volume=None, volume_to=None, index=0):
        self.name = name #Название главы или тома
        self.content = content #Содержание
        self.chapters = [] #Для подглав
        self.volume = volume
        self.volume_to = volume_to
        self.index = index

    def append(self, chapter):
        self.chapters.append(chapter)

    def __repr__(self):
        return '\n{}: {}'.format(self.name, self.chapters if self.chapters else '')

class Book:
    def __init__(self, id_, session=None):
        self.id = id_
        self.base_url = 'https://tl.rulate.ru'
        self.url = self.base_url + '/book/{}'.format(id_)
        self.title = None #Название
        self.img_url = None #Cсылка на картинку
        self.description = None #Описание
        self.chapters = [] #Главы
        self.rows = []
        self.img_urls = []
        self.pictures = []
        self.session = session
        self.load_main()
    
    def load_main(self):
        page = self.get(self.url) #Download page
        info = parse_page_info.search(page) #Find all info on page
        if info:
            self.title = info['title']
            self.img_url = info['img']
            self.description = info['description']
            count = 0
            for one in parse_chapters.finditer(page): #Parse rows from document
                self.rows.append(Row(one, index=count)) #Create Row and save to list
                count += 1
            
    def add_to_chapters(self, chapter_):
        if chapter_.volume_to: #Is connected
            for chapter in self.chapters: #Check chapter to connect
                if chapter.volume and chapter.volume == chapter_.volume_to: #Finded
                    chapter.append(chapter_) #Connecting
                    return
        self.chapters.append(chapter_) #Add to main
            
    def load_chapters(self):
        async def fetch_get(row, session):
            if row.is_chapter:
                async with session.get(self.base_url + row.url) as resp:
                    return Chapter(row.name, self.check_chapter_content(await resp.text()), volume_to=row.volume_to, index=row.index)
            else:
                return Chapter(row.name, volume=row.volume, index=row.index)
        async def get_pages(list_):
            async with aiohttp.ClientSession(headers=self.session.headers if self.session else {}, cookies=self.session.cookies if self.session else {}) as session:
                return await asyncio.gather(*[asyncio.ensure_future(fetch_get(one, session)) for one in list_])
        for chapter in sorted(asyncio.new_event_loop().run_until_complete(get_pages(self.rows)), key=lambda c: c.index):
            self.add_to_chapters(chapter)

    def from_url_to_filename(self, url):
        return url.replace('/', '')
            
    def check_picture_in_content(self, content):
        for url in img_pattern.finditer(content): #Finding <img src="...." />
            if not url[1] in self.img_urls: #If new picture (some pictures can repeat)
                self.img_urls.append(url[1])
            content = content.replace(url[0], '<image l:href=\"#{}\"/>'.format(self.from_url_to_filename(url[1]))) #Replace to fb2 type
        return content

    def convert_pic_to_jpg_n_encode_to_base64(self, pic_content):
        buffer = BytesIO(pic_content) #Load picture from response to buffer
        img = Image.open(buffer) #Load from buffer
        new_img = img.convert('RGB')#To ignore error with RGBA
        new_img.save(buffer, format='JPEG') #Format picture to .jpg
        return base64.b64encode(buffer.getvalue()).decode() #Encode to base64 and return as string

    def check_chapter_content(self, page): #Fixing errors in text
        content = parse_chapter_content.search(page) if page else None
        if content:
            content = content[1]
            content = ''.join([part.split('<!--')[0] for part in content.split('-->')])
            content = self.check_picture_in_content(content)
        return content
    
    def load_pictures(self):
        async def fetch_get(url, session):
            async with session.get(self.base_url + url) as resp:
                return Picture(self.from_url_to_filename(url), 'image/jpeg', self.convert_pic_to_jpg_n_encode_to_base64(await resp.read())) #Encode to base64
        async def get_pics(list_):
            async with aiohttp.ClientSession() as session:
                return await asyncio.gather(*[asyncio.ensure_future(fetch_get(one, session)) for one in list_])
        self.img_urls.append(self.img_url) #Add to all_pictures thumbnail_url
        self.pictures = asyncio.new_event_loop().run_until_complete(get_pics(self.img_urls))

    async def auth(self, session):
        async with session.post(self.base_url, data={'login[login]': self.session.login, 'login[pass]': self.session.password}) as resp:
            return await resp.text()

    async def approve_book(self, session):
        async with session.post(self.base_url + '/mature?path={}'.format(self.id), data={'path': '/book/{}'.format(self.id), 'ok': 'Да'}) as resp:
            return await resp.text()

    def get(self, url):
        async def fetch_get(url, session):
            async with session.get(url) as resp:
                return await resp.text()
        async def gget(url):
            async with aiohttp.ClientSession(headers=self.session.headers if self.session else {}, cookies=self.session.cookies if self.session else {}) as session:
                if self.session:
                    await self.auth(session)
                    await self.approve_book(session)
                    self.session.set_cookies(session)
                return await fetch_get(url, session)
        return asyncio.new_event_loop().run_until_complete(gget(url))

    def fb2_serialize(self):
        book = FB2book(self.title, self.url, self.from_url_to_filename(self.img_url))
        for chapter in self.chapters:
            book.add_chapter(chapter)
        for pic in self.pictures:
            book.add_picture(pic)
        return book.result()

    def format_to_fb2(self, filename=None, io=False):
        self.load_chapters()
        self.load_pictures()
        fb2_result = self.fb2_serialize()
        if filename:
            with open(filename, 'wb') as f:
                f.write(fb2_result)
        elif io:
            return BytesIO(fb2_result)
        else:
            return fb2_result

class Session:
    def __init__(self, login, password):
        self.login = login
        self.password = password
        self.headers = {}
        self.cookies = {}

    def set_cookies(self, session):
        self.cookies = {cookie.key:cookie.value for cookie in session.cookie_jar}

if __name__ == '__main__':
    session = None #Session('login', 'password')
    book_id = 24
    book = Book(book_id, session)
    print(book.title)
    book.format_to_fb2('bookname.fb2')

