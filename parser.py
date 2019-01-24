import re
import asyncio
import aiohttp
import io
from PIL import Image
import base64
from fb2book import FB2book

parse_page_info = re.compile(r'\<h1\>(?P<title>.+)\<\/h1\>\n\<div\sid\=\'Info\'[\s\S]+\<img\ssrc\=\"(?P<img>\/i\/book\/[a-z0-9\/\.]+)\"[\s\S]+(?P<description>\<p\>\<strong\>Автор\:\<\/strong\>\s\<em\>\<a\shref\=.+)\n')

parse_chapters = re.compile(r'\<tr\sid\=\'(c\_|vol\_title\_)(?P<index>[0-9]+)\'[^>]*class\=\'(?P<type>chapter\_row|volume_helper)\s?(?P<volume_to>[^\' ]*)\s?\'\>\<td(\scolspan\=\'14\'\sonclick\=\'\$\(\".(?P<volume>volume\_[0-9a-z]+)\"\)[^<]+\<strong\>(?P<title>[^<]+)|\>\<\/td\>\<td\sclass\=\'t\'\>\<a\shref\=\'(?P<url>[^\']+)\'\>(?P<name>[^<]+)\<\/a\>)')

parse_chapter_content = re.compile(r'\<div\sid\=\"readpage\"\>([\S\s]+)\<\/div\>\n\<div\sstyle\=\"text\-align\:\scenter\;\smargin\-bottom\:\s20px\;\"')

img_pattern = re.compile(r'\<img\ssrc\=\"([^\"]+)\"\s*\/\>')

class Picture:
    def __init__(self, name, type_, content):
        self.name = name
        self.type = type_
        self.content = content

class Row:
    def __init__(self, result):
        self.is_chapter = result['type'] == 'chapter_row'
        self.url = result['url'] if self.is_chapter else None
        self.name = result['name'] if self.is_chapter else result['title']
        self.index = result['index']
        self.volume = result['volume'] if not self.is_chapter else None
        self.volume_to = result['volume_to'] if self.is_chapter else None

    def __repr__(self):
        return '{} № {}\nName: {}\nUrl: {}\nVolume_to: {}\nVolume: {}'.format(
            'Chapter' if self.is_chapter else 'Volume',
            self.index,
            self.name,
            self.url,
            self.volume_to,
            self.volume)

class Chapter:
    def __init__(self, name, page=None, volume=None, volume_to=None, index=0):
        self.name = name #Название главы или тома
        finded = parse_chapter_content.search(page) if page else None
        self.content = finded[1] if finded else None #Содержимое главы (если пусто/разделитель - None)
        self.chapters = [] #Для подглав
        self.volume = volume
        self.volume_to = volume_to
        self.index = index

    def append(self, chapter):
        self.chapters.append(chapter)

    def __repr__(self):
        return '\n{}: {}'.format(self.name, self.chapters if self.chapters else '')

class Book:
    def __init__(self, id_):
        self.title = None #Название
        self.img_url = None #Cсылка на картинку
        self.description = None #Описание
        self.chapters = [] #Главы
        self.rows = []
        self.base_url = 'https://tl.rulate.ru'
        self.img_urls = []
        self.pictures = []
        self.load_rows(self.load_page(id_))
        self.load_chapters()
        self.find_pictures()
        self.load_pictures()
        
    def load_page(self, id_):
        return self.get(self.base_url + '/book/{}'.format(id_))

    def load_rows(self, page):
        info = parse_page_info.search(page)
        self.title = info['title']
        self.img_url = info['img']
        self.description = info['description']
        count = 0
        for one in parse_chapters.finditer(page):
            row = Row(one)
            row.index = count
            count += 1
            self.rows.append(row)
            
    def add_to_chapters(self, chapter_):
        if chapter_.volume_to: 
            for chapter in self.chapters:
                if chapter.volume and chapter.volume == chapter_.volume_to:
                    chapter.append(chapter_)
                    break
        else:
            self.chapters.append(chapter_)
            
    def load_chapters(self):
        self.chapters = []
        async def fetch_get(row, session):
            if row.is_chapter:
                async with session.get(self.base_url + row.url) as resp:
                    return Chapter(row.name, await resp.text(), volume_to=row.volume_to, index=row.index)
            else:
                return Chapter(row.name, volume=row.volume, index=row.index)
        async def get_pages(list_):
            async with aiohttp.ClientSession() as session:
                return await asyncio.gather(*[asyncio.ensure_future(fetch_get(one, session)) for one in list_])
        for chapter in sorted(asyncio.new_event_loop().run_until_complete(get_pages(self.rows)), key=lambda c: c.index):
            self.add_to_chapters(chapter)

    def find_pictures(self):
        for chapter in self.chapters:
            if chapter.content:
                for url in img_pattern.finditer(chapter.content):
                    new_url = url[1].replace('/', '')
                    if not url[1] in self.img_urls:
                        self.img_urls.append(url[1])
                    chapter.content = chapter.content.replace(url[0], '<image l:href=\"#{}\"/>'.format(new_url))
    
    def load_pictures(self):
        async def fetch_get(url, session):
            async with session.get(self.base_url + url) as resp:
                buffer = io.BytesIO(await resp.read())
                image = Image.open(buffer)
                image.save(buffer, format="JPEG")
                return Picture(url.replace('/', ''), 'image/jpeg', base64.b64encode(buffer.getvalue()).decode())
        async def get_pics(list_):
            async with aiohttp.ClientSession() as session:
                return await asyncio.gather(*[asyncio.ensure_future(fetch_get(one, session)) for one in list_])
        self.img_urls.append(self.img_url)
        self.pictures = asyncio.new_event_loop().run_until_complete(get_pics(self.img_urls))
                    
    def get(self, url):
        async def fetch_get(url, session):
            async with session.get(url) as resp:
                return await resp.text()
        async def gget(url):
            async with aiohttp.ClientSession() as session:
                return await fetch_get(url, session)
        return asyncio.new_event_loop().run_until_complete(gget(url))

    def fb2(self):
        book = FB2book(self.title, 'Will be later?', self.img_url.replace('/', ''))
        for chapter in self.chapters:
            book.add_chapter(chapter)
        for pic in self.pictures:
            book.add_picture(pic)
        return book.result()

if __name__ == '__main__':
    book = Book(341)
    with open('book.fb2', 'wb') as f:
        f.write(book.fb2())
