import scrapy
from bs4 import BeautifulSoup
import os
import img2pdf
from urllib.parse import urljoin
from ..database import MangaDatabase

class MangahindisubSpider(scrapy.Spider):
    name = "mangahindisub"
    allowed_domains = ["mangahindisub.in"]

    def __init__(self, url=None, output_pdf=None, *args, **kwargs):
        super(MangahindisubSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url] if url else []
        self.output_pdf = output_pdf or "output.pdf"
        self.db = MangaDatabase()

    def parse(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        img_tags = soup.find_all('img')
        temp_folder = "temp_images"
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
        self.image_paths = []
        base_url = response.url

        for idx, img in enumerate(img_tags):
            img_url = urljoin(base_url, img.get('src'))
            if not img_url:
                continue
            yield scrapy.Request(img_url, callback=self.save_image, meta={'idx': idx, 'folder': temp_folder})

    def save_image(self, response):
        idx = response.meta['idx']
        folder = response.meta['folder']
        img_path = os.path.join(folder, f"image_{idx}.jpg")
        with open(img_path, 'wb') as f:
            f.write(response.body)
        self.image_paths.append(img_path)
        if len(self.image_paths) == len([i for i in response.meta.get('idx', [])]):  # Last image
            with open(self.output_pdf, "wb") as f:
                f.write(img2pdf.convert(self.image_paths))
            self.db.add_download(response.url, self.output_pdf)
            for p in self.image_paths:
                os.remove(p)
            os.rmdir(folder)
            self.db.close()
