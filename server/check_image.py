import os
from PIL import Image

icon_path = r"c:\xampp\htdocs\projects\tssidekick\extension\icon.png"

if os.path.exists(icon_path):
    try:
        img = Image.open(icon_path)
        print(f"Format: {img.format}")
        print(f"Size: {img.size}")
        print(f"Mode: {img.mode}")
        
        # Save resized versions
        img.resize((128, 128), Image.Resampling.LANCZOS).save(os.path.join(os.path.dirname(icon_path), "icon128.png"))
        img.resize((48, 48), Image.Resampling.LANCZOS).save(os.path.join(os.path.dirname(icon_path), "icon48.png"))
        img.resize((16, 16), Image.Resampling.LANCZOS).save(os.path.join(os.path.dirname(icon_path), "icon16.png"))
        print("Icons resized and saved successfully.")
    except Exception as e:
        print(f"Error processing image: {e}")
else:
    print("Icon file not found.")
