from django import template
from django.utils.safestring import mark_safe
import os
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

register = template.Library()

@register.filter
def resize_image(image_field, size="600x400"):
    """
    Resize image to specified dimensions
    Usage: {{ image.url|resize_image:"600x400" }}
    """
    if not image_field:
        return ""
    
    try:
        # Open the image
        img = Image.open(image_field.path)
        
        # Parse size
        width, height = map(int, size.split('x'))
        
        # Resize image
        img.thumbnail((width, height), Image.Resampling.LANCZOS)
        
        # Save to bytes
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)
        
        # Create a temporary file name
        filename = f"resized_{os.path.basename(image_field.name)}"
        
        # Save the resized image
        saved_path = default_storage.save(f"resized/{filename}", ContentFile(output.read()))
        
        return default_storage.url(saved_path)
        
    except Exception as e:
        # Return original if resize fails
        return image_field.url