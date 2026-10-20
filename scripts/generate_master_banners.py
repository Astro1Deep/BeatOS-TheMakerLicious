#!/usr/bin/env python3
"""
Generate Master Technical Banner Variants for BeatOS — The MakerLicious
Using authentic Swiss modernist typography (Helvetica Neue), hairline millimeter grid,
and 100% faithful orthographic product cutouts from official hardware references.
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

def create_banner(variant_name, mpc_key, mpc_title, mpc_sub, sheet_num, out_path):
    # Canvas Dimensions (16:9 QHD high resolution)
    W, H = 2560, 1440
    bg_color = (245, 245, 247) # TE Drafting Paper Off-White
    
    # Initialize base canvas
    banner = Image.new('RGB', (W, H), bg_color)
    draw = ImageDraw.Draw(banner)
    
    # 1. Draw subtle hairline millimeter grid (TE drafting paper aesthetic)
    grid_color = (235, 235, 238)
    major_grid_color = (225, 225, 230)
    for x in range(0, W, 40):
        color = major_grid_color if x % 200 == 0 else grid_color
        draw.line([(x, 0), (x, H)], fill=color, width=1)
    for y in range(0, H, 40):
        color = major_grid_color if y % 200 == 0 else grid_color
        draw.line([(0, y), (W, y)], fill=color, width=1)
        
    # Technical border
    margin = 40
    draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=(205, 205, 212), width=1)
    
    # Corner registration marks (+)
    reg_size = 8
    corners = [
        (margin + 10, margin + 10),
        (W - margin - 10, margin + 10),
        (margin + 10, H - margin - 10),
        (W - margin - 10, H - margin - 10)
    ]
    for cx, cy in corners:
        draw.line([(cx - reg_size, cy), (cx + reg_size, cy)], fill=(150, 150, 158), width=1)
        draw.line([(cx, cy - reg_size), (cx, cy + reg_size)], fill=(150, 150, 158), width=1)
        
    # Fonts
    ttc = '/System/Library/Fonts/HelveticaNeue.ttc'
    font_header_title = ImageFont.truetype(ttc, 28, index=10) # Medium
    font_header_sub = ImageFont.truetype(ttc, 18, index=7)   # Light
    font_sheet = ImageFont.truetype(ttc, 24, index=1)         # Bold
    font_badge = ImageFont.truetype(ttc, 16, index=10)        # Medium
    font_station_num = ImageFont.truetype(ttc, 22, index=1)   # Bold
    font_station_sub = ImageFont.truetype(ttc, 15, index=0)   # Regular
    font_footer_main = ImageFont.truetype(ttc, 20, index=1)   # Bold
    font_footer_sub = ImageFont.truetype(ttc, 16, index=0)    # Regular
    font_footer_dim = ImageFont.truetype(ttc, 14, index=7)    # Light
    
    # 2. Header Serigraphy
    header_y = margin + 25
    draw.text((margin + 25, header_y), "beatos labs // universal beatmaker specification", fill=(18, 18, 20), font=font_header_title)
    draw.text((margin + 25, header_y + 36), "the makerlicious · 16-pad tactile matrix & audio engine architecture", fill=(110, 110, 118), font=font_header_sub)
    
    # Sheet badge
    sheet_text = f"sheet {sheet_num:02d} of 03 // rev 2.4"
    draw.text((W - margin - 380, header_y + 6), sheet_text, fill=(255, 102, 0), font=font_sheet) # Orange PO
    
    # Dividing rule below header
    draw.line([(margin + 20, header_y + 75), (W - margin - 20, header_y + 75)], fill=(215, 215, 222), width=1)
    
    # 3. 5 Station Layout
    # Column centers
    col_width = (W - 2 * margin - 80) / 5
    col_centers = [int(margin + 40 + (i + 0.5) * col_width) for i in range(5)]
    
    stations = [
        {
            "id": "01",
            "name": "01 / pocket operator",
            "sub": "PO-33 K.O.! · micro sampler",
            "img_key": "po33",
            "max_h": 680,
            "max_w": 380
        },
        {
            "id": "02",
            "name": "02 / ep-133 k.o. ii",
            "sub": "128 MB SAMPLER COMPOSER",
            "img_key": "ep133",
            "max_h": 690,
            "max_w": 440
        },
        {
            "id": "03",
            "name": mpc_title,
            "sub": mpc_sub,
            "img_key": mpc_key,
            "max_h": 690,
            "max_w": 450
        },
        {
            "id": "04",
            "name": "04 / roland sp-404mk2",
            "sub": "177 × 276 mm · oled porthole",
            "img_key": "sp404",
            "max_h": 700,
            "max_w": 420
        },
        {
            "id": "05",
            "name": "05 / ni maschine",
            "sub": "MK3 · dual screens & 8 encoders",
            "img_key": "maschine",
            "max_h": 680,
            "max_w": 450
        }
    ]
    
    hardware_base_y = 1140 # Optical baseline
    station_label_y = header_y + 105
    
    cuts_dir = '/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c'
    
    for idx, st in enumerate(stations):
        cx = col_centers[idx]
        
        # Draw Station Label
        # Pill badge
        draw.text((cx - 130, station_label_y), st["name"], fill=(18, 18, 20), font=font_station_num)
        draw.text((cx - 130, station_label_y + 30), st["sub"], fill=(120, 120, 128), font=font_station_sub)
        
        # Load cut image
        cut_p = f"{cuts_dir}/perfect_cut_{st['img_key']}.png"
        if not os.path.exists(cut_p):
            print(f"Warning: {cut_p} not found")
            continue
            
        cut_img = Image.open(cut_p).convert('RGBA')
        orig_w, orig_h = cut_img.size
        
        # Scale keeping aspect ratio
        scale = min(st["max_w"] / orig_w, st["max_h"] / orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        scaled_img = cut_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        pos_x = cx - new_w // 2
        pos_y = hardware_base_y - new_h
        
        # Soft contact shadow
        shadow_w, shadow_h = int(new_w * 0.95), 24
        shadow = Image.new('RGBA', (shadow_w, shadow_h), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow)
        s_draw.ellipse([(0, 0), (shadow_w, shadow_h)], fill=(0, 0, 0, 45))
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        banner.paste(shadow, (cx - shadow_w // 2, hardware_base_y - 12), shadow)
        
        # Paste hardware
        banner.paste(scaled_img, (pos_x, pos_y), scaled_img)
        
        # Millimeter coordinate tick under station
        draw.line([(cx - 20, hardware_base_y + 20), (cx + 20, hardware_base_y + 20)], fill=(180, 180, 188), width=1)
        draw.line([(cx, hardware_base_y + 15), (cx, hardware_base_y + 25)], fill=(180, 180, 188), width=1)
        
    # 4. Footer Serigraphy
    footer_y = H - margin - 150
    draw.line([(margin + 20, footer_y), (W - margin - 20, footer_y)], fill=(215, 215, 222), width=1)
    
    draw.text((margin + 25, footer_y + 20), f"hardware guide specification // sheet {sheet_num:02d} of 03", fill=(18, 18, 20), font=font_footer_main)
    footer_stations_str = f"[A] pocket operator · [B] ep-133 · [C] {st_short(mpc_key)} · [D] roland sp-404mk2 · [E] ni maschine"
    draw.text((margin + 25, footer_y + 50), footer_stations_str, fill=(70, 70, 78), font=font_footer_sub)
    draw.text((margin + 25, footer_y + 78), "16-pad unified fingerdrumming architecture · beatos the makerlicious edition", fill=(120, 120, 128), font=font_footer_dim)
    
    # Right badge
    badge_x = W - margin - 460
    draw.rectangle([(badge_x, footer_y + 25), (W - margin - 25, footer_y + 65)], outline=(255, 102, 0), width=1)
    draw.text((badge_x + 16, footer_y + 34), "[ 44.1 kHz / 16-BIT PCM · STEREO SAMPLER ENGINE ]", fill=(255, 102, 0), font=font_badge)
    
    # Save output
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    banner.save(out_path, quality=96)
    print(f"Generated: {out_path} ({W}x{H})")

def st_short(key):
    if key == "mpc_sample":
        return "akai mpc sample"
    elif key == "mpc_one":
        return "akai mpc one"
    elif key == "mpc_live3":
        return "akai mpc live iii"
    return "akai mpc"

if __name__ == "__main__":
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    
    # 1. Variant 1: MPC Sample Edition
    create_banner(
        variant_name="Edition MPC Sample",
        mpc_key="mpc_sample",
        mpc_title="03 / akai mpc sample",
        mpc_sub="AC50 · 4×4 rgb pads & fader",
        sheet_num=1,
        out_path=f"{out_dir}/banner_variant_01_mpc_sample.jpg"
    )
    
    # 2. Variant 2: MPC One Edition
    create_banner(
        variant_name="Edition MPC One",
        mpc_key="mpc_one",
        mpc_title="03 / akai mpc one",
        mpc_sub="G2 · 7\" touch & 4 q-links",
        sheet_num=2,
        out_path=f"{out_dir}/banner_variant_02_mpc_one.jpg"
    )
    
    # 3. Variant 3: MPC Live III Edition
    create_banner(
        variant_name="Edition MPC Live III",
        mpc_key="mpc_live3",
        mpc_title="03 / akai mpc live iii",
        mpc_sub="retro · full stereo speakers",
        sheet_num=3,
        out_path=f"{out_dir}/banner_variant_03_mpc_live3.jpg"
    )
    
    # Also save Variant 1 as the default master banner: te_universal_beatmaker_banner.jpg
    import shutil
    shutil.copyfile(f"{out_dir}/banner_variant_01_mpc_sample.jpg", f"{out_dir}/te_universal_beatmaker_banner.jpg")
    print(f"Copied Variant 1 to {out_dir}/te_universal_beatmaker_banner.jpg")
