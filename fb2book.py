class FB2book:
    def __init__(self, title, author, thumbnail=None):
        self.title = title
        self.thumbnail = thumbnail
        self.publisher = 'DALOR'
        self.tags = []
        self.authors = []
        self.chapters = []
        self.pictures = []
        self.author = author
        self.add_author(author)

    def add_author(self, author):
        self.authors.append('<first-name></first-name><last-name>{}</last-name>'.format(author))

    def add_tag(self, tag):
        self.tags.append(tag)

    def format_chapter(self, chapter):
        return '''
<section>
    <title><p>{}</p></title>
    {}
    {}
</section>
'''.format(chapter.name, chapter.content if chapter.content else '', '\n'.join([self.format_chapter(ch) for ch in chapter.chapters]))
    
    def add_chapter(self, chapter):
        self.chapters.append(self.format_chapter(chapter))

    def add_picture(self, pic):
        self.pictures.append('<binary id="{}" content-type="{}">{}</binary>'.format(pic.name, pic.type, pic.content))
    
    def result(self):
        return '''
<?xml version="1.0" encoding="UTF-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
	<description>
		<title-info>
			<genre>
				{}
			</genre>
			<author>
                                {}
			</author>
			<book-title>
				{}
			</book-title>
			{}
		</title-info>
		<document-info>
			<author>
				<nickname>
					{}
				</nickname>
			</author>
		</document-info>
		<publish-info>
			<publisher>
				{}
			</publisher>
		</publish-info>
	</description>
<body>
{}
</body>
{}	
</FictionBook>'''.format(
    ', '.join(self.tags),
    '\n'.join(self.authors),
    self.title,
    '<coverpage><image l:href="#{}" /></coverpage>'.format(self.thumbnail) if self.thumbnail else '',
    self.author,
    self.publisher,
    '\n'.join(self.chapters),
    '\n'.join(self.pictures)
    ).encode()
