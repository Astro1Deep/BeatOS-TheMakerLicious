#!/usr/bin/env python3
"""
Build Master Technical Blueprint Banner for BeatOS — The MakerLicious
100% faithful to the physical hardware references, zero mutilated components,
centered prominent header, zero unwanted Teenage Engineering PO sheet copies,
and solid, homogeneous contours for all 5 stations.
"""

import os
import shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

def clean_device_extractions(ref_dir, scratch_dir):
    os.makedirs(scratch_dir, exist_ok=True)
    
    # 1. PO-33 K.O.! (po33_blueprint_te_style.jpg)
    # Full hanger loop (y=48..140) and full PCB (y=140..1080)
    # 100% intact, no chopped loop, no overlaps
    im_po = Image.open(os.path.join(ref_dir, "po33_blueprint_te_style.jpg"))
    crop_po = im_po.crop((210, 48, 685, 1080)).convert("RGBA")
    arr_po = np.array(crop_po)
    bg_po = np.array([241, 241, 237])
    for y in range(80):
        for x in range(crop_po.width):
            if x < 85 or x > 385 or np.linalg.norm(arr_po[y, x, :3] - bg_po) < 20:
                arr_po[y, x, 3] = 0
    arr_po[80:, :10, 3] = 0
    arr_po[80:, 464:, 3] = 0
    arr_po[1022:, :, 3] = 0
    clean_po = Image.fromarray(arr_po)
    po_path = os.path.join(scratch_dir, "blueprint_clean_po33.png")
    clean_po.save(po_path)

    # 2. Akai MPC Sample (akai_mpc_sample_blueprint_topdown_te_style.jpg)
    # Full chassis from x=220 to 832, y=102 to 756
    # Complete volume knob, fader, display, pads, jog wheel, logos
    im_mpc = Image.open(os.path.join(ref_dir, "akai_mpc_sample_blueprint_topdown_te_style.jpg"))
    crop_mpc = im_mpc.crop((220, 102, 832, 756)).convert("RGBA")
    arr_mpc = np.array(crop_mpc)
    arr_mpc[:, :8, 3] = 0
    arr_mpc[:, 605:, 3] = 0
    arr_mpc[:8, :, 3] = 0
    arr_mpc[647:, :, 3] = 0
    clean_mpc = Image.fromarray(arr_mpc)
    mpc_path = os.path.join(scratch_dir, "blueprint_clean_mpc.png")
    clean_mpc.save(mpc_path)

    # 3. Roland SP-404MK2 (roland_sp404mk2_blueprint_te_style.jpg)
    # Full chassis from x=178 to 672, y=162 to 1162
    # All 4 top knobs (VOLUME, CTRL 1-3), logos, circular OLED, 16 pads, solid contour
    im_sp = Image.open(os.path.join(ref_dir, "roland_sp404mk2_blueprint_te_style.jpg"))
    crop_sp = im_sp.crop((178, 162, 672, 1162)).convert("RGBA")
    arr_sp = np.array(crop_sp)
    arr_sp[:4, :, 3] = 0
    arr_sp[996:, :, 3] = 0
    arr_sp[:, :3, 3] = 0
    arr_sp[:, 491:, 3] = 0
    clean_sp = Image.fromarray(arr_sp)
    sdraw = ImageDraw.Draw(clean_sp)
    sdraw.rounded_rectangle([(3, 4), (clean_sp.width - 4, 995)], radius=14, outline=(22, 22, 24, 255), width=2)
    sp_path = os.path.join(scratch_dir, "blueprint_clean_sp404.png")
    clean_sp.save(sp_path)

    # 4. NI Maschine MK3 (maschine_blueprint_te_style_from_user_photo.jpg)
    # Full chassis from x=132 to 890, y=175 to 865
    # All 8 buttons above dual screens, encoders, 16 pads, 4D dial
    im_mas = Image.open(os.path.join(ref_dir, "maschine_blueprint_te_style_from_user_photo.jpg"))
    crop_mas = im_mas.crop((132, 175, 890, 865)).convert("RGBA")
    arr_mas = np.array(crop_mas)
    arr_mas[:7, :, 3] = 0
    arr_mas[683:, :, 3] = 0
    arr_mas[:, :5, 3] = 0
    arr_mas[:, 751:, 3] = 0
    clean_mas = Image.fromarray(arr_mas)
    mas_path = os.path.join(scratch_dir, "blueprint_clean_maschine.png")
    clean_mas.save(mas_path)

    # 5. Teenage Engineering EP-133 K.O. II (ep133_blueprint_te_style.jpg)
    # Full chassis with top connector tabs from x=64 to 880, y=48 to 1152
    im_ep = Image.open(os.path.join(ref_dir, "ep133_blueprint_te_style.jpg"))
    crop_ep = im_ep.crop((64, 48, 880, 1152)).convert("RGBA")
    arr_ep = np.array(crop_ep)
    bg_ep = np.array([241, 241, 241])
    for y in range(12):
        for x in range(crop_ep.width):
            if np.linalg.norm(arr_ep[y, x, :3] - bg_ep) < 20:
                arr_ep[y, x, 3] = 0
    arr_ep[:, :4, 3] = 0
    arr_ep[:, 812:, 3] = 0
    arr_ep[1106:, :, 3] = 0
    clean_ep = Image.fromarray(arr_ep)
    ep_path = os.path.join(scratch_dir, "blueprint_clean_ep133.png")
    clean_ep.save(ep_path)

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

    print("Preparing 5 authentic blueprints with ZERO cuts and solid contours...")
    paths = clean_device_extractions(ref_dir, scratch_dir)

    W, H = 2560, 1440
    bg_color = (244, 243, 240)

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

    # Outer margin & boundary
    margin = 44
    draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=(200, 199, 194), width=1)

    # Corner registration marks (+)
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

    # Swiss Modernist Typography (Helvetica Neue)
    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"
    font_title = ImageFont.truetype(ttc, 44, index=1)       # Bold
    font_system = ImageFont.truetype(ttc, 22, index=10)     # Medium
    font_ref = ImageFont.truetype(ttc, 16, index=7)         # Light/Mono
    font_st_label = ImageFont.truetype(ttc, 22, index=1)    # Bold
    font_footer_spec = ImageFont.truetype(ttc, 20, index=1) # Bold
    font_footer_stations = ImageFont.truetype(ttc, 18, index=10) # Medium
    font_footer_arch = ImageFont.truetype(ttc, 15, index=7) # Light
    font_badge = ImageFont.truetype(ttc, 16, index=10)      # Medium

    # 1. HEADER (STRICTLY CENTERED AND PROMINENT, NO UNWANTED TOP-RIGHT COPYCAT BLOCK)
    title_txt = "BeatOS — The MakerLicious"
    bbox = font_title.getbbox(title_txt)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, margin + 26), title_txt, fill=(18, 18, 20), font=font_title)

    sys_txt = "The system ★ [universal beatmaker station]"
    bbox_sys = font_system.getbbox(sys_txt)
    draw.text(((W - (bbox_sys[2] - bbox_sys[0])) // 2, margin + 82), sys_txt, fill=(255, 102, 0), font=font_system)

    ref_txt = "│ ref: mpc · sp-404 · pocket operator · maschine │"
    bbox_ref = font_ref.getbbox(ref_txt)
    draw.text(((W - (bbox_ref[2] - bbox_ref[0])) // 2, margin + 116), ref_txt, fill=(110, 110, 118), font=font_ref)

    # Dividing rule below header
    draw.line([(margin + 20, margin + 154), (W - margin - 20, margin + 154)], fill=(210, 210, 215), width=1)

    # 2. 5 HARDWARE STATIONS IN STRICT ORDER
    stations = [
        {"name": "01 / pocket operator", "key": "po33", "target_w": 327, "target_h": 710},
        {"name": "02 / akai mpc", "key": "mpc", "target_w": 450, "target_h": 481},
        {"name": "03 / roland sp-404mk2", "key": "sp404", "target_w": 361, "target_h": 730},
        {"name": "04 / ni maschine", "key": "maschine", "target_w": 470, "target_h": 428},
        {"name": "05 / ep-133 k.o. ii", "key": "ep133", "target_w": 517, "target_h": 700}
    ]

    col_width = (W - 2 * margin - 80) / 5
    col_centers = [int(margin + 40 + (i + 0.5) * col_width) for i in range(5)]
    hardware_base_y = 1200
    label_y = margin + 185

    for i, st in enumerate(stations):
        cx = col_centers[i]
        
        # Station label with ample clearance (over 200px above hardware)
        bbox_l = font_st_label.getbbox(st["name"])
        tw = bbox_l[2] - bbox_l[0]
        draw.text((cx - tw // 2, label_y), st["name"], fill=(18, 18, 20), font=font_st_label)
        draw.line([(cx - 18, label_y - 8), (cx + 18, label_y - 8)], fill=(255, 102, 0), width=2)
        
        # Load and scale clean device
        dev_path = paths[st["key"]]
        dev_img = Image.open(dev_path).convert("RGBA")
        scaled = dev_img.resize((st["target_w"], st["target_h"]), Image.Resampling.LANCZOS)
        
        pos_x = cx - st["target_w"] // 2
        pos_y = hardware_base_y - st["target_h"]
        
        # Technical soft contact shadow at baseline
        sh_w, sh_h = int(st["target_w"] * 0.94), 22
        shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, 42))
        shadow = shadow.filter(ImageFilter.GaussianBlur(7))
        banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 10), shadow)
        
        # Paste clean, uncut device
        banner.paste(scaled, (pos_x, pos_y), scaled)
        
        # Millimeter calibration crosshair under station
        draw.line([(cx - 20, hardware_base_y + 18), (cx + 20, hardware_base_y + 18)], fill=(180, 180, 185), width=1)
        draw.line([(cx, hardware_base_y + 10), (cx, hardware_base_y + 26)], fill=(180, 180, 185), width=1)

    # 3. FOOTER
    footer_y = H - margin - 120
    draw.line([(margin + 20, footer_y), (W - margin - 20, footer_y)], fill=(210, 210, 215), width=1)

    draw.text((margin + 36, footer_y + 16), "hardware guide specification // universal beatmaker station", fill=(18, 18, 20), font=font_footer_spec)
    stations_footer = "[A] pocket operator · [B] akai mpc · [C] roland sp-404mk2 · [D] ni maschine · [E] ep-133 k.o. ii"
    draw.text((margin + 36, footer_y + 44), stations_footer, fill=(255, 102, 0), font=font_footer_stations)
    draw.text((margin + 36, footer_y + 72), "16-pad unified fingerdrumming architecture", fill=(110, 110, 118), font=font_footer_arch)

    # Right tech spec badge
    rx1 = W - margin - 470
    draw.rectangle([(rx1, footer_y + 22), (W - margin - 36, footer_y + 68)], outline=(255, 102, 0), width=1)
    draw.text((rx1 + 18, footer_y + 35), "[ 44.1 kHz / 16-BIT PCM · HARDWARE MATRIX ]", fill=(255, 102, 0), font=font_badge)

    # 4. SAVE TO ALL OFFICIAL BRANDING ASSETS
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(brain_dir, exist_ok=True)

    master_jpg = os.path.join(out_dir, "te_universal_beatmaker_banner.jpg")
    banner.save(master_jpg, quality=98)
    print(f"Saved: {master_jpg}")

    var01_jpg = os.path.join(out_dir, "banner_variant_01_mpc_sample.jpg")
    banner.save(var01_jpg, quality=98)
    print(f"Saved: {var01_jpg}")

    bp_jpg = os.path.join(out_dir, "banner_blueprint_edition.jpg")
    banner.save(bp_jpg, quality=98)
    print(f"Saved: {bp_jpg}")

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
