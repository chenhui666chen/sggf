# -*- coding: utf-8 -*-
"""创建测试用图片资源"""
import sys
sys.path.insert(0, '.')

from PIL import Image
import os

test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_fixtures')
os.makedirs(test_dir, exist_ok=True)

# 创建一张测试用图片 (1024x1024)
img = Image.new('RGB', (1024, 1024), color=(70, 130, 180))
from PIL import ImageDraw, ImageFont
draw = ImageDraw.Draw(img)
draw.text((400, 500), "TEST IMAGE", fill=(255, 255, 255))
img.save(os.path.join(test_dir, 'test_image.png'))
print(f"Test image created: {os.path.join(test_dir, 'test_image.png')}")

# 创建不同比例的测试图片
for ratio, (w, h) in [('16:9', (1024, 576)), ('9:16', (576, 1024)), ('1:1', (1024, 1024))]:
    img = Image.new('RGB', (w, h), color=(100, 150, 200))
    draw = ImageDraw.Draw(img)
    draw.text((w//4, h//2), f"TEST {ratio}", fill=(255, 255, 255))
    img.save(os.path.join(test_dir, f'test_{ratio.replace(":","_")}.png'))
    print(f"Created: test_{ratio.replace(':','_')}.png")

print("All test fixtures created successfully!")
