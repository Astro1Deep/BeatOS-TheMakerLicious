#!/usr/bin/env python3
"""
Build Master Technical Blueprint Banner Suite for BeatOS — The MakerLicious
Generates 100% faithful banners tailored for ALL 6 ecosystem themes:
1. te-arcade (Flagship TE PO-33 Arcade Dark - #0d0f14)
2. cerebro-neon (Cyberpunk Astro1Deep - #090c12)
3. mpc-vintage (Akai MPC Vintage - #16171a)
4. sp404-studio (Roland SP-404MK2 - #08090c)
5. maschine-studio (NI Maschine Studio - #101114)
6. makerlicious-bone (The MakerLicious Bone Glitch / Blanco Roto - #f4f3f0)

Zero mutilated hardware, centered prominent header, zero unwanted PO sheet copycats,
and 100% solid, homogeneous contours across all devices.
"""

import os
import shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

def prepare_clean_devices(ref_dir, scratch_dir):
    os.makedirs(scratch_dir, exist_ok=True)
    
    # 1. PO-33 K.O.! (po33_blueprint_te_style.jpg)
    # Full wire hanger loop (y=48..140) and full PCB (y=140..1080)
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

    # Build dark theme variants
    def convert_to_dark(src_img, dest_path, target_bg_rgb=(20, 23, 32)):
        arr = np.array(src_img, dtype=float)
        alpha = arr[:, :, 3]
        rgb = arr[:, :, :3]
        lum = 0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]
        max_c = rgb.max(axis=2)
        min_c = rgb.min(axis=2)
        sat = np.where(max_c > 0, (max_c - min_c) / np.maximum(max_c, 1), 0)
        is_gray = sat < 0.22
        mapped_gray = 242.0 - (lum / 242.0) * (242.0 - target_bg_rgb[0])
        mapped_gray = np.clip(mapped_gray, target_bg_rgb[0], 245)
        dark_rgb = rgb.copy()
        for c in range(3):
            dark_rgb[:, :, c] = np.where(is_gray, mapped_gray, rgb[:, :, c])
        dark_arr = np.dstack([dark_rgb, alpha]).astype(np.uint8)
        dark_im = Image.fromarray(dark_arr)
        dark_im.save(dest_path)
        return dest_path

    dark_mpc_path = convert_to_dark(clean_mpc, os.path.join(scratch_dir, "dark_clean_mpc.png"), (20, 23, 32))
    dark_sp_path = convert_to_dark(clean_sp, os.path.join(scratch_dir, "dark_clean_sp404.png"), (16, 17, 24))
    dark_mas_path = convert_to_dark(clean_mas, os.path.join(scratch_dir, "dark_clean_maschine.png"), (18, 19, 26))
    dark_ep_path = convert_to_dark(clean_ep, os.path.join(scratch_dir, "dark_clean_ep133.png"), (22, 24, 30))

    return {
        "bone": {
            "po33": po_path,
            "mpc": mpc_path,
            "sp404": sp_path,
            "maschine": mas_path,
            "ep133": ep_path
        },
        "dark": {
            "po33": po_path,
            "mpc": dark_mpc_path,
            "sp404": dark_sp_path,
            "maschine": dark_mas_path,
            "ep133": dark_ep_path
        }
    }

def build_all_theme_banners():
    ref_dir = "/Users/ivan/Downloads/BEATMAKER HARDWARES REF"
    scratch_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/scratch"
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    brain_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(brain_dir, exist_ok=True)

    print("Extracting clean devices and preparing dark/bone palettes...")
    devices = prepare_clean_devices(ref_dir, scratch_dir)

    themes = [
        {
            "id": "te-arcade",
            "name": "TE PO-33 K.O.! (Flagship Dark)",
            "bg": (13, 15, 20),
            "grid": (25, 30, 43),
            "major_grid": (37, 44, 61),
            "border": (43, 50, 66),
            "text_main": (245, 245, 247),
            "accent": (255, 102, 0),
            "subtext": (140, 147, 163),
            "is_dark": True,
            "filename": "banner_theme_te_arcade.jpg"
        },
        {
            "id": "cerebro-neon",
            "name": "Cerebro OS Neon",
            "bg": (9, 12, 18),
            "grid": (20, 28, 42),
            "major_grid": (30, 44, 66),
            "border": (36, 44, 61),
            "text_main": (255, 255, 255),
            "accent": (0, 240, 255),
            "subtext": (126, 139, 155),
            "is_dark": True,
            "filename": "banner_theme_cerebro_neon.jpg"
        },
        {
            "id": "mpc-vintage",
            "name": "Akai MPC Vintage",
            "bg": (22, 23, 26),
            "grid": (34, 36, 42),
            "major_grid": (48, 51, 60),
            "border": (56, 59, 68),
            "text_main": (240, 236, 225),
            "accent": (214, 40, 40),
            "subtext": (156, 154, 146),
            "is_dark": True,
            "filename": "banner_theme_mpc_vintage.jpg"
        },
        {
            "id": "sp404-studio",
            "name": "Roland SP-404MK2 Studio",
            "bg": (8, 9, 12),
            "grid": (20, 22, 30),
            "major_grid": (34, 37, 51),
            "border": (34, 37, 51),
            "text_main": (237, 242, 244),
            "accent": (255, 153, 0),
            "subtext": (125, 130, 144),
            "is_dark": True,
            "filename": "banner_theme_sp404_studio.jpg"
        },
        {
            "id": "maschine-studio",
            "name": "NI Maschine Studio",
            "bg": (16, 17, 20),
            "grid": (28, 30, 37),
            "major_grid": (45, 49, 61),
            "border": (45, 49, 61),
            "text_main": (255, 255, 255),
            "accent": (58, 134, 255),
            "subtext": (139, 143, 156),
            "is_dark": True,
            "filename": "banner_theme_maschine_studio.jpg"
        },
        {
            "id": "makerlicious-bone",
            "name": "The MakerLicious (Bone Glitch / Blanco Roto)",
            "bg": (244, 243, 240),
            "grid": (235, 234, 230),
            "major_grid": (222, 221, 216),
            "border": (200, 199, 194),
            "text_main": (18, 18, 20),
            "accent": (255, 102, 0),
            "subtext": (110, 110, 118),
            "is_dark": False,
            "filename": "banner_blueprint_edition.jpg"
        }
    ]

    W, H = 2560, 1440
    margin = 44

    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"
    font_title = ImageFont.truetype(ttc, 44, index=1)
    font_system = ImageFont.truetype(ttc, 22, index=10)
    font_ref = ImageFont.truetype(ttc, 16, index=7)
    font_st_label = ImageFont.truetype(ttc, 22, index=1)
    font_footer_spec = ImageFont.truetype(ttc, 20, index=1)
    font_footer_stations = ImageFont.truetype(ttc, 18, index=10)
    font_footer_arch = ImageFont.truetype(ttc, 15, index=7)
    font_badge = ImageFont.truetype(ttc, 16, index=10)

    col_width = (W - 2 * margin - 80) / 5
    col_centers = [int(margin + 40 + (i + 0.5) * col_width) for i in range(5)]
    hardware_base_y = 1200
    label_y = margin + 185

    stations_def = [
        {"name": "01 / pocket operator", "key": "po33", "target_w": 327, "target_h": 710},
        {"name": "02 / akai mpc", "key": "mpc", "target_w": 450, "target_h": 481},
        {"name": "03 / roland sp-404mk2", "key": "sp404", "target_w": 361, "target_h": 730},
        {"name": "04 / ni maschine", "key": "maschine", "target_w": 470, "target_h": 428},
        {"name": "05 / ep-133 k.o. ii", "key": "ep133", "target_w": 517, "target_h": 700}
    ]

    for th in themes:
        banner = Image.new("RGB", (W, H), th["bg"])
        draw = ImageDraw.Draw(banner)

        # Hairline millimeter grid
        for x in range(0, W, 40):
            c = th["major_grid"] if x % 200 == 0 else th["grid"]
            draw.line([(x, 0), (x, H)], fill=c, width=1)
        for y in range(0, H, 40):
            c = th["major_grid"] if y % 200 == 0 else th["grid"]
            draw.line([(0, y), (W, y)], fill=c, width=1)

        # Outer border
        draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=th["border"], width=1)

        # Corner registration crosshairs (+)
        reg = 10
        corners = [
            (margin + 12, margin + 12),
            (W - margin - 12, margin + 12),
            (margin + 12, H - margin - 12),
            (W - margin - 12, H - margin - 12)
        ]
        cross_col = (130, 130, 135) if not th["is_dark"] else (100, 108, 125)
        for cx, cy in corners:
            draw.line([(cx - reg, cy), (cx + reg, cy)], fill=cross_col, width=1)
            draw.line([(cx, cy - reg), (cx, cy + reg)], fill=cross_col, width=1)

        # 1. Centered Header
        title_txt = "BeatOS — The MakerLicious"
        bbox = font_title.getbbox(title_txt)
        draw.text(((W - (bbox[2] - bbox[0])) // 2, margin + 26), title_txt, fill=th["text_main"], font=font_title)

        sys_txt = "The system ★ [universal beatmaker station]"
        bbox_sys = font_system.getbbox(sys_txt)
        draw.text(((W - (bbox_sys[2] - bbox_sys[0])) // 2, margin + 82), sys_txt, fill=th["accent"], font=font_system)

        ref_txt = "│ ref: mpc · sp-404 · pocket operator · maschine │"
        bbox_ref = font_ref.getbbox(ref_txt)
        draw.text(((W - (bbox_ref[2] - bbox_ref[0])) // 2, margin + 116), ref_txt, fill=th["subtext"], font=font_ref)

        draw.line([(margin + 20, margin + 154), (W - margin - 20, margin + 154)], fill=th["border"], width=1)

        # 2. Hardware Stations
        dev_map = devices["dark"] if th["is_dark"] else devices["bone"]
        for i, st in enumerate(stations_def):
            cx = col_centers[i]
            
            # Label
            bbox_l = font_st_label.getbbox(st["name"])
            tw = bbox_l[2] - bbox_l[0]
            draw.text((cx - tw // 2, label_y), st["name"], fill=th["text_main"], font=font_st_label)
            draw.line([(cx - 18, label_y - 8), (cx + 18, label_y - 8)], fill=th["accent"], width=2)
            
            # Device
            img_path = dev_map[st["key"]]
            dev_img = Image.open(img_path).convert("RGBA")
            scaled = dev_img.resize((st["target_w"], st["target_h"]), Image.Resampling.LANCZOS)
            
            pos_x = cx - st["target_w"] // 2
            pos_y = hardware_base_y - st["target_h"]
            
            # Contact Shadow
            sh_w, sh_h = int(st["target_w"] * 0.94), 22
            shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow)
            alpha_val = 130 if th["is_dark"] else 42
            sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, alpha_val))
            shadow = shadow.filter(ImageFilter.GaussianBlur(8))
            banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 10), shadow)
            
            # Paste Device
            banner.paste(scaled, (pos_x, pos_y), scaled)
            
            # Technical crosshair
            draw.line([(cx - 20, hardware_base_y + 18), (cx + 20, hardware_base_y + 18)], fill=cross_col, width=1)
            draw.line([(cx, hardware_base_y + 10), (cx, hardware_base_y + 26)], fill=cross_col, width=1)

        # 3. Footer
        footer_y = H - margin - 120
        draw.line([(margin + 20, footer_y), (W - margin - 20, footer_y)], fill=th["border"], width=1)

        draw.text((margin + 36, footer_y + 16), "hardware guide specification // universal beatmaker station", fill=th["text_main"], font=font_footer_spec)
        stations_footer = "[A] pocket operator · [B] akai mpc · [C] roland sp-404mk2 · [D] ni maschine · [E] ep-133 k.o. ii"
        draw.text((margin + 36, footer_y + 44), stations_footer, fill=th["accent"], font=font_footer_stations)
        draw.text((margin + 36, footer_y + 72), "16-pad unified fingerdrumming architecture", fill=th["subtext"], font=font_footer_arch)

        rx1 = W - margin - 470
        draw.rectangle([(rx1, footer_y + 22), (W - margin - 36, footer_y + 68)], outline=th["accent"], width=1)
        draw.text((rx1 + 18, footer_y + 35), "[ 44.1 kHz / 16-BIT PCM · HARDWARE MATRIX ]", fill=th["accent"], font=font_badge)

        # Save themed banner
        out_p = os.path.join(out_dir, th["filename"])
        banner.save(out_p, quality=98)
        print(f"Generated theme banner for {th['name']} -> {out_p}")

        # Sync key aliases
        if th["id"] == "te-arcade":
            # Flagship Default
            shutil.copy2(out_p, os.path.join(out_dir, "te_universal_beatmaker_banner.jpg"))
            shutil.copy2(out_p, os.path.join(out_dir, "banner_variant_01_mpc_sample.jpg"))
            shutil.copy2(out_p, os.path.join(brain_dir, "te_universal_beatmaker_banner.jpg"))
            banner.save(os.path.join(out_dir, "te_universal_beatmaker_banner_preview.png"), format="PNG")
            banner.save(os.path.join(brain_dir, "te_universal_beatmaker_banner_preview.png"), format="PNG")
        elif th["id"] == "makerlicious-bone":
            # Bone Edition
            shutil.copy2(out_p, os.path.join(out_dir, "te_universal_beatmaker_banner_bone.jpg"))
            shutil.copy2(out_p, os.path.join(brain_dir, "banner_blueprint_edition.jpg"))
            banner.save(os.path.join(out_dir, "te_universal_beatmaker_blueprint_edition.png"), format="PNG")
            banner.save(os.path.join(brain_dir, "te_universal_beatmaker_blueprint_edition.png"), format="PNG")

    print("All 6 theme banners created and synchronized successfully!")

if __name__ == "__main__":
    build_all_theme_banners()
