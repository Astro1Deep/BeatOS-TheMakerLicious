#!/usr/bin/env python3
"""
Build Authentic Master Technical Blueprint Banner for BeatOS — The MakerLicious
Using official Teenage Engineering manual style blueprints from /Users/ivan/Downloads/BEATMAKER HARDWARES REF
100% faithful to the physical hardware, homogeneous styling, zero stray lines, zero artificial bounding boxes.
"""

import os
import shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

def extract_and_prepare_devices(ref_dir, scratch_dir):
    os.makedirs(scratch_dir, exist_ok=True)
    
    # 1. PO-33 K.O.! (from po33_blueprint_te_style.jpg)
    # Includes full top wire hanger loop (y=62..140) and full PCB (y=140..1073, x=218..677)
    # Zero artificial lines, natural PCB contours and components 100% preserved.
    im_po = Image.open(os.path.join(ref_dir, "po33_blueprint_te_style.jpg"))
    crop_po = im_po.crop((218, 62, 677, 1073)).convert("RGBA")
    arr_po = np.array(crop_po)
    bg_po = np.array([241, 240, 236])
    
    # Clear empty space outside hanger loop above PCB (y < 78)
    for y in range(78):
        for x in range(crop_po.width):
            if x < 85 or x > 335 or np.linalg.norm(arr_po[y, x, :3] - bg_po) < 15:
                arr_po[y, x, 3] = 0
                
    # Clear empty margin outside PCB borders
    arr_po[78:, :2, 3] = 0
    arr_po[78:, 457:, 3] = 0
    
    # Clear empty space outside bottom rounded corners
    for y in range(1000, crop_po.height):
        for x in list(range(20)) + list(range(crop_po.width - 20, crop_po.width)):
            if np.linalg.norm(arr_po[y, x, :3] - bg_po) < 15:
                arr_po[y, x, 3] = 0
                
    crop_po = Image.fromarray(arr_po)
    po_path = os.path.join(scratch_dir, "blueprint_prep_po33.png")
    crop_po.save(po_path)

    # 2. Akai MPC Sample (from akai_mpc_sample_blueprint_topdown_te_style.jpg)
    # Start at y=120 to eliminate the stray y=110 guideline completely (Image 0).
    # Clear stray leader lines outside the chassis to the left of x=40 below bezel (Image 1).
    # Zero artificial border rectangles.
    im_mpc = Image.open(os.path.join(ref_dir, "akai_mpc_sample_blueprint_topdown_te_style.jpg"))
    crop_mpc = im_mpc.crop((246, 120, 827, 750)).convert("RGBA")
    arr_mpc = np.array(crop_mpc)
    arr_mpc[175:, :40, 3] = 0
    crop_mpc = Image.fromarray(arr_mpc)
    mpc_path = os.path.join(scratch_dir, "blueprint_prep_mpc.png")
    crop_mpc.save(mpc_path)

    # 3. Roland SP-404MK2 (from roland_sp404mk2_blueprint_te_style.jpg)
    # Natural blueprint linework with circular OLED screen centered horizontally.
    # Clean outside the 4 rounded corners. Zero artificial drawn rectangles.
    im_sp = Image.open(os.path.join(ref_dir, "roland_sp404mk2_blueprint_te_style.jpg"))
    crop_sp = im_sp.crop((180, 208, 670, 1132)).convert("RGBA")
    arr_sp = np.array(crop_sp)
    bg_sp = np.array([242, 239, 226])
    for y in range(35):
        for x in range(35):
            if np.linalg.norm(arr_sp[y, x, :3] - bg_sp) < 18:
                arr_sp[y, x, 3] = 0
        for x in range(crop_sp.width - 35, crop_sp.width):
            if np.linalg.norm(arr_sp[y, x, :3] - bg_sp) < 18:
                arr_sp[y, x, 3] = 0
    for y in range(crop_sp.height - 35, crop_sp.height):
        for x in range(35):
            if np.linalg.norm(arr_sp[y, x, :3] - bg_sp) < 18:
                arr_sp[y, x, 3] = 0
        for x in range(crop_sp.width - 35, crop_sp.width):
            if np.linalg.norm(arr_sp[y, x, :3] - bg_sp) < 18:
                arr_sp[y, x, 3] = 0
    crop_sp = Image.fromarray(arr_sp)
    sp_path = os.path.join(scratch_dir, "blueprint_prep_sp404.png")
    crop_sp.save(sp_path)

    # 4. NI Maschine MK3 (from maschine_blueprint_te_style_from_user_photo.jpg)
    # Natural blueprint linework with dual screens, 8 encoders, 4D encoder, 16 RGB pads.
    # Zero artificial lines.
    im_mas = Image.open(os.path.join(ref_dir, "maschine_blueprint_te_style_from_user_photo.jpg"))
    crop_mas = im_mas.crop((137, 198, 885, 862)).convert("RGBA")
    mas_path = os.path.join(scratch_dir, "blueprint_prep_maschine.png")
    crop_mas.save(mas_path)

    # 5. Teenage Engineering EP-133 K.O. II (from ep133_blueprint_te_style.jpg)
    # Authentic chassis, top tabs, calculator keys, fader, Knobs X/Y.
    # Clear paper background between connector tabs at y < 32. Zero artificial lines.
    im_ep = Image.open(os.path.join(ref_dir, "ep133_blueprint_te_style.jpg"))
    crop_ep = im_ep.crop((67, 80, 828, 1076)).convert("RGBA")
    arr_ep = np.array(crop_ep)
    bg_ep = np.array([241, 241, 241])
    for y in range(32):
        diff = np.linalg.norm(arr_ep[y, :, :3] - bg_ep, axis=1)
        arr_ep[y, diff < 12, 3] = 0
    crop_ep = Image.fromarray(arr_ep)
    ep_path = os.path.join(scratch_dir, "blueprint_prep_ep133.png")
    crop_ep.save(ep_path)

    return {
        "po33": po_path,
        "mpc": mpc_path,
        "sp404": sp_path,
        "maschine": mas_path,
        "ep133": ep_path
    }

def build_master_blueprint_banner():
    ref_dir = "/Users/ivan/Downloads/BEATMAKER HARDWARES REF"
    scratch_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/scratch"
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    brain_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"
    
    print("Preparing 5 authentic blueprints from official reference sheets...")
    paths = extract_and_prepare_devices(ref_dir, scratch_dir)

    W, H = 2560, 1440
    bg_color = (244, 243, 240) # Authentic Teenage Engineering bone-white drafting paper

    banner = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(banner)

    # Hairline millimeter grid
    grid_color = (235, 234, 230)
    major_grid = (222, 221, 216)
    for x in range(0, W, 40):
        c = major_grid if x % 200 == 0 else grid_color
        draw.line([(x, 0), (x, H)], fill=c, width=1)
    for y in range(0, H, 40):
        c = major_grid if y % 200 == 0 else grid_color
        draw.line([(0, y), (W, y)], fill=c, width=1)

    # Outer margin & border
    margin = 44
    draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=(200, 199, 194), width=1)

    # Corner registration crosses (+)
    reg = 10
    corners = [
        (margin + 12, margin + 12),
        (W - margin - 12, margin + 12),
        (margin + 12, H - margin - 12),
        (W - margin - 12, H - margin - 12)
    ]
    for cx, cy in corners:
        draw.line([(cx - reg, cy), (cx + reg, cy)], fill=(130, 130, 135), width=1)
        draw.line([(cx, cy - reg), (cx, cy + reg)], fill=(130, 130, 135), width=1)

    # Typography (Swiss Modernist / Helvetica Neue)
    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"
    font_main_title = ImageFont.truetype(ttc, 36, index=1)   # Bold
    font_system = ImageFont.truetype(ttc, 20, index=10)       # Medium
    font_ref = ImageFont.truetype(ttc, 16, index=7)          # Light / Mono
    font_sheet = ImageFont.truetype(ttc, 20, index=1)        # Bold Orange
    font_st_label = ImageFont.truetype(ttc, 22, index=1)     # Bold Station Label
    font_footer_spec = ImageFont.truetype(ttc, 20, index=1)  # Bold
    font_footer_stations = ImageFont.truetype(ttc, 18, index=10) # Medium
    font_footer_arch = ImageFont.truetype(ttc, 15, index=7)  # Light

    # 1. Header (User exact specifications)
    draw.text((margin + 36, margin + 28), "BeatOS — The MakerLicious", fill=(18, 18, 20), font=font_main_title)
    draw.text((margin + 36, margin + 74), "The system ★ [universal beatmaker station]", fill=(255, 102, 0), font=font_system)
    draw.text((margin + 36, margin + 104), "│ ref: mpc · sp-404 · pocket operator · maschine │", fill=(110, 110, 118), font=font_ref)

    draw.text((W - margin - 380, margin + 34), "beatos labs // specification", fill=(18, 18, 20), font=font_system)
    draw.text((W - margin - 380, margin + 64), "sheet 01 of 01 // rev 2026", fill=(255, 102, 0), font=font_sheet)

    draw.line([(margin + 20, margin + 140), (W - margin - 20, margin + 140)], fill=(210, 210, 215), width=1)

    # 2. Balanced Stations Layout (5 Hardware stations in strict exact order)
    stations = [
        {"name": "01 / pocket operator", "key": "po33", "target_w": 285, "target_h": 628},
        {"name": "02 / akai mpc", "key": "mpc", "target_w": 445, "target_h": 482},
        {"name": "03 / roland sp-404mk2", "key": "sp404", "target_w": 345, "target_h": 650},
        {"name": "04 / ni maschine", "key": "maschine", "target_w": 465, "target_h": 413},
        {"name": "05 / ep-133 k.o. ii", "key": "ep133", "target_w": 455, "target_h": 596}
    ]

    col_width = (W - 2 * margin - 80) / 5
    col_centers = [int(margin + 40 + (i + 0.5) * col_width) for i in range(5)]
    hardware_base_y = 1170
    label_y = margin + 175

    for i, st in enumerate(stations):
        cx = col_centers[i]
        
        # Station label (Clean and direct, NO subtitles)
        bbox = font_st_label.getbbox(st["name"])
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, label_y), st["name"], fill=(18, 18, 20), font=font_st_label)
        draw.line([(cx - 18, label_y - 10), (cx + 18, label_y - 10)], fill=(255, 102, 0), width=2)
        
        # Load and scale blueprint device
        img_p = paths[st["key"]]
        img = Image.open(img_p).convert("RGBA")
        nw, nh = st["target_w"], st["target_h"]
        scaled = img.resize((nw, nh), Image.Resampling.LANCZOS)
        
        pos_x = cx - nw // 2
        pos_y = hardware_base_y - nh
        
        # Technical soft contact shadow
        sh_w, sh_h = int(nw * 0.95), 24
        shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, 48))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 12), shadow)
        
        # Paste the pure, clean blueprint device
        banner.paste(scaled, (pos_x, pos_y), scaled)
        
        # Millimeter calibration crosshair under station
        draw.line([(cx - 20, hardware_base_y + 20), (cx + 20, hardware_base_y + 20)], fill=(180, 180, 185), width=1)
        draw.line([(cx, hardware_base_y + 12), (cx, hardware_base_y + 28)], fill=(180, 180, 185), width=1)

    # 3. Footer (Exact user specification)
    footer_y = H - margin - 130
    draw.line([(margin + 20, footer_y), (W - margin - 20, footer_y)], fill=(210, 210, 215), width=1)

    draw.text((margin + 36, footer_y + 18), "hardware guide specification // sheet 01 of 01", fill=(18, 18, 20), font=font_footer_spec)
    stations_footer = "[A] pocket operator · [B] akai mpc · [C] roland sp-404mk2 · [D] ni maschine · [E] ep-133 k.o. ii"
    draw.text((margin + 36, footer_y + 48), stations_footer, fill=(255, 102, 0), font=font_footer_stations)
    draw.text((margin + 36, footer_y + 78), "16-pad unified fingerdrumming architecture", fill=(110, 110, 118), font=font_footer_arch)

    # Right tech spec badge
    rx1 = W - margin - 460
    draw.rectangle([(rx1, footer_y + 25), (W - margin - 36, footer_y + 72)], outline=(255, 102, 0), width=1)
    draw.text((rx1 + 18, footer_y + 38), "[ 44.1 kHz / 16-BIT PCM · HARDWARE MATRIX ]", fill=(255, 102, 0), font=font_system)

    # 4. Save to official destinations
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(brain_dir, exist_ok=True)
    
    # Save Master Technical Blueprint Banner
    master_jpg = os.path.join(out_dir, "te_universal_beatmaker_banner.jpg")
    banner.save(master_jpg, quality=98)
    print(f"Saved: {master_jpg}")
    
    # Variant 01 (MPC Sample)
    var01_jpg = os.path.join(out_dir, "banner_variant_01_mpc_sample.jpg")
    banner.save(var01_jpg, quality=98)
    print(f"Saved: {var01_jpg}")

    # Blueprint edition alias
    bp_jpg = os.path.join(out_dir, "banner_blueprint_edition.jpg")
    banner.save(bp_jpg, quality=98)
    print(f"Saved: {bp_jpg}")

    # Preview PNG
    preview_png = os.path.join(out_dir, "te_universal_beatmaker_banner_preview.png")
    banner.save(preview_png, format="PNG")
    print(f"Saved: {preview_png}")

    bp_png = os.path.join(out_dir, "te_universal_beatmaker_blueprint_edition.png")
    banner.save(bp_png, format="PNG")
    print(f"Saved: {bp_png}")

    # Copy to artifacts brain directory
    shutil.copy2(master_jpg, os.path.join(brain_dir, "te_universal_beatmaker_banner.jpg"))
    shutil.copy2(preview_png, os.path.join(brain_dir, "te_universal_beatmaker_banner_preview.png"))
    shutil.copy2(bp_jpg, os.path.join(brain_dir, "banner_blueprint_edition.jpg"))
    print("Copied master banners to brain artifacts directory.")

if __name__ == "__main__":
    build_master_blueprint_banner()
