#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeChat Article Image Scraper and PDF Generator

This script scrapes images from a WeChat public account article and 
generates a PDF file containing all the images.
"""

import os
import requests
import re
import time
import uuid
from bs4 import BeautifulSoup
import img2pdf
from io import BytesIO
from PIL import Image
import logging
import base64
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WeChatImageScraper:
    """Scrapes images from WeChat public account articles and creates PDFs."""
    
    def __init__(self, url, output_dir="output", pdf_name="wechat_article.pdf"):
        """
        Initialize the scraper with URL and output settings.
        
        Args:
            url (str): URL of the WeChat article
            output_dir (str): Directory to save downloaded images
            pdf_name (str): Name of the output PDF file
        """
        self.url = url
        self.output_dir = output_dir
        self.pdf_name = pdf_name
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.driver = None
        
        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created output directory: {output_dir}")
    
    def setup_webdriver(self):
        """Set up and return a headless Chrome webdriver."""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument(f"user-agent={self.headers['User-Agent']}")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Successfully set up Chrome webdriver")
            return True
        except Exception as e:
            logger.error(f"Error setting up Chrome webdriver: {e}")
            return False
    
    def load_article(self):
        """Load the article and wait for content to be rendered."""
        try:
            logger.info(f"Loading article at {self.url}")
            self.driver.get(self.url)
            
            # Wait for the page to load completely
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Scroll down to load lazy-loaded images
            self.scroll_to_load_images()
            
            return True
        except Exception as e:
            logger.error(f"Error loading article: {e}")
            return False
    
    def scroll_to_load_images(self):
        """Scroll through the page to ensure all lazy-loaded images are loaded."""
        try:
            # Get scroll height
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            
            for _ in range(5):  # Scroll multiple times to ensure everything loads
                # Scroll down to bottom
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                
                # Wait to load page
                time.sleep(2)
                
                # Calculate new scroll height and compare with last scroll height
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                
            # Scroll back to top
            self.driver.execute_script("window.scrollTo(0, 0);")
            
            # Gradually scroll down to load all images
            height = self.driver.execute_script("return document.body.scrollHeight")
            for i in range(10):
                self.driver.execute_script(f"window.scrollTo(0, {height * i / 10});")
                time.sleep(0.5)
            
            logger.info("Scrolled through page to load all images")
            return True
        except Exception as e:
            logger.error(f"Error during scrolling: {e}")
            return False
    
    def extract_images_with_selenium(self):
        """
        Extract images directly using Selenium.
        
        Returns:
            list: List of image URLs found in the article
        """
        try:
            # Execute JavaScript to find all images in the article
            js_script = """
            var images = [];
            // Regular img tags
            var imgElements = document.querySelectorAll('img');
            imgElements.forEach(function(img) {
                // Skip small images (likely icons)
                if (img.width >= 100 && img.height >= 100) {
                    var src = img.src || img.getAttribute('data-src') || img.getAttribute('data-original');
                    if (src) {
                        images.push({
                            url: src,
                            width: img.width,
                            height: img.height
                        });
                    }
                }
            });
            
            // WeChat specific: data-src attributes are commonly used
            var wechatImgs = document.querySelectorAll('[data-src]');
            wechatImgs.forEach(function(img) {
                var dataSrc = img.getAttribute('data-src');
                if (dataSrc && !images.some(i => i.url === dataSrc)) {
                    images.push({
                        url: dataSrc,
                        width: img.width || 0,
                        height: img.height || 0
                    });
                }
            });
            
            // Sometimes images are in background-image CSS
            var elementsWithBackgroundImg = document.querySelectorAll('*');
            elementsWithBackgroundImg.forEach(function(element) {
                var style = window.getComputedStyle(element);
                var backgroundImage = style.backgroundImage;
                if (backgroundImage && backgroundImage !== 'none') {
                    var match = backgroundImage.match(/url\(['"]?(.*?)['"]?\)/);
                    if (match && match[1]) {
                        var url = match[1];
                        // Only include if it's a reasonable size element
                        if (element.offsetWidth >= 100 && element.offsetHeight >= 100) {
                            images.push({
                                url: url,
                                width: element.offsetWidth,
                                height: element.offsetHeight
                            });
                        }
                    }
                }
            });
            
            return images;
            """
            
            image_data = self.driver.execute_script(js_script)
            
            # Process and filter image URLs
            image_urls = []
            for img in image_data:
                url = img.get('url', '')
                
                # Skip data URLs
                if url.startswith('data:'):
                    continue
                    
                # Handle relative URLs
                if url.startswith('//'):
                    url = 'https:' + url
                elif not (url.startswith('http://') or url.startswith('https://')):
                    if url.startswith('/'):
                        parsed_url = urlparse(self.url)
                        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                        url = base_url + url
                    else:
                        url = urljoin(self.url, url)
                
                # Add to list if not already there
                if url and url not in image_urls:
                    image_urls.append(url)
            
            logger.info(f"Found {len(image_urls)} images in the article using Selenium")
            return image_urls
            
        except Exception as e:
            logger.error(f"Error extracting images with Selenium: {e}")
            return []
    
    def download_images(self, image_urls):
        """
        Download images from the extracted URLs.
        
        Args:
            image_urls (list): List of image URLs to download
            
        Returns:
            list: Paths to the downloaded image files
        """
        if not image_urls:
            return []
            
        downloaded_images = []
        
        for i, url in enumerate(image_urls):
            try:
                logger.info(f"Downloading image {i+1}/{len(image_urls)}: {url}")
                
                # Try screenshot method if traditional download fails
                try:
                    response = requests.get(url, headers=self.headers, timeout=30)
                    response.raise_for_status()
                    image_content = response.content
                except:
                    logger.warning(f"Failed to download image via requests, trying alternative method")
                    continue
                
                try:
                    # Try to open as image to verify it's valid
                    img = Image.open(BytesIO(image_content))
                    
                    # Skip too small images (likely icons, buttons, etc.)
                    if img.width < 100 or img.height < 100:
                        logger.warning(f"Skipping small image: {img.width}x{img.height}")
                        continue
                        
                    # Generate filename and path
                    filename = f"image_{i+1:03d}.jpg"
                    filepath = os.path.join(self.output_dir, filename)
                    
                    # Convert to RGB if needed and save
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.save(filepath, 'JPEG')
                    
                    downloaded_images.append(filepath)
                    logger.info(f"Saved image to {filepath}")
                    
                except Exception as e:
                    logger.warning(f"Failed to process image from {url}: {e}")
                    continue
                
            except Exception as e:
                logger.error(f"Error downloading image {url}: {e}")
                continue
        
        # If no images were downloaded via normal means, try taking screenshots
        if not downloaded_images and self.driver:
            try:
                logger.info("Attempting to capture article content via screenshots")
                downloaded_images = self.capture_article_screenshots()
            except Exception as e:
                logger.error(f"Error capturing screenshots: {e}")
        
        return downloaded_images
    
    def capture_article_screenshots(self):
        """Capture article content via screenshots as a fallback method."""
        screenshot_paths = []
        
        try:
            # Try to locate the main article content
            article_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                                                        "#js_content, .rich_media_content, article, .content")
            
            if not article_elements:
                # If can't find specific content div, use body
                article_elements = [self.driver.find_element(By.TAG_NAME, "body")]
                
            main_element = article_elements[0]
            
            # Get the height and set a reasonable viewport
            total_height = main_element.size['height']
            viewport_height = 1000  # A reasonable chunk size
            
            # Take screenshots in chunks
            for i in range(0, total_height, viewport_height):
                # Scroll to position
                self.driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.5)  # Give time for rendering
                
                # Take screenshot
                screenshot = self.driver.get_screenshot_as_png()
                img = Image.open(BytesIO(screenshot))
                
                # Save screenshot
                filepath = os.path.join(self.output_dir, f"screenshot_{i//viewport_height:03d}.jpg")
                img.save(filepath, 'JPEG')
                screenshot_paths.append(filepath)
                
                logger.info(f"Captured screenshot at scroll position {i}")
            
            return screenshot_paths
            
        except Exception as e:
            logger.error(f"Error capturing article screenshots: {e}")
            return []
    
    def create_pdf(self, image_paths):
        """
        Create a PDF file from the downloaded images.
        
        Args:
            image_paths (list): List of paths to image files
            
        Returns:
            str: Path to the created PDF file
        """
        if not image_paths:
            logger.error("No images to create PDF from")
            return None
        
        pdf_path = os.path.join(self.output_dir, self.pdf_name)
        
        try:
            # Convert images to PDF-compatible format
            converted_images = []
            for img_path in image_paths:
                try:
                    # Open image, convert to RGB if needed
                    img = Image.open(img_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Save as temporary JPEG
                    temp_path = img_path.replace('.jpg', '_temp.jpg')
                    img.save(temp_path, 'JPEG')
                    converted_images.append(temp_path)
                except Exception as e:
                    logger.error(f"Error converting image {img_path}: {e}")
                    continue
            
            # Create PDF
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert(converted_images))
            
            logger.info(f"Created PDF at {pdf_path}")
            
            # Clean up temporary files
            for temp_img in converted_images:
                if os.path.exists(temp_img) and '_temp.jpg' in temp_img:
                    os.remove(temp_img)
            
            return pdf_path
        
        except Exception as e:
            logger.error(f"Error creating PDF: {e}")
            return None
    
    def run(self):
        """
        Run the full scraping and PDF creation process.
        
        Returns:
            str: Path to the created PDF file, or None if the process failed
        """
        logger.info(f"Starting to scrape images from {self.url}")
        
        # Set up webdriver
        if not self.setup_webdriver():
            return None
        
        try:
            # Load the article
            if not self.load_article():
                return None
            
            # Extract image URLs using Selenium
            image_urls = self.extract_images_with_selenium()
            
            # Download images
            image_paths = self.download_images(image_urls)
            if not image_paths:
                logger.error("Failed to download any images")
                return None
            
            # Create PDF
            pdf_path = self.create_pdf(image_paths)
            
            return pdf_path
            
        finally:
            # Clean up webdriver
            if self.driver:
                self.driver.quit()
                logger.info("Closed webdriver")


def main():
    """Main function to run the scraper."""
    # WeChat article URL from the requirements
    url = "https://mp.weixin.qq.com/s?__biz=MzU5OTYxODY1Mw==&mid=2247534100&idx=4&sn=89ce4d8da316c9c85d9261ef81f933e6&chksm=feb02326c9c7aa308d829d3bb79ec7cc39e1100a4f7026a92d9c1ce6b60d4845e980803a3591&scene=21#wechat_redirect"
    
    # Initialize and run the scraper
    scraper = WeChatImageScraper(url)
    pdf_path = scraper.run()
    
    if pdf_path:
        logger.info(f"Successfully created PDF at {pdf_path}")
    else:
        logger.error("Failed to create PDF")


if __name__ == "__main__":
    main()
