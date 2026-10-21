#!/usr/bin/env python3
"""
Build Master Technical Blueprint Banner Suite for BeatOS — The MakerLicious
Generates 100% faithful, non-mutilated technical banners for ALL 6 ecosystem themes:
1. te-arcade (Flagship TE PO-33 Arcade Dark - #0d0f14)
2. cerebro-neon (Cyberpunk Astro1Deep - #090c12)
3. mpc-vintage (Akai MPC Vintage - #16171a)
4. sp404-studio (Roland SP-404MK2 - #08090c)
5. maschine-studio (NI Maschine Studio - #101114)
6. makerlicious-bone (The MakerLicious Bone Glitch / Blanco Roto - #f4f3f0)

CRITICAL CRITERIA:
- CERO RECORTES: Every instrument has 100% of its physical chassis, buttons, knobs, and contours intact.
- CERO COLISIONES: Minimum 120 px of clear breathing room between every pair of instruments.
- CERO CAJAS RECTANGULARES: 100% alpha transparency outside every chassis so the banner background flows seamlessly.
- HOMOGENEIDAD TOTAL: In dark themes, all 5 instruments are rendered with uniform dark surface & crisp light linework.
- ENCABEZADO CENTRADO: BeatOS — The MakerLicious centered at x=1280.
"""

import os
import shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

def extract_and_prepare_all_devices(ref_dir, scratch_dir):
    os.makedirs(scratch_dir, exist_ok=True)
    
    # 1. PO-33 K.O.! (po33_blueprint_te_style.jpg)
    # Bbox: (218, 62, 677, 1073) -> (459 x 1011)
    im_po = Image.open(os.path.join(ref_dir, "po33_blueprint_te_style.jpg"))
    crop_po = im_po.crop((218, 62, 677, 1073)).convert("RGB")
    w_po, h_po = crop_po.size
    mask_po = Image.new("L", (w_po, h_po), 0)
    d_po = ImageDraw.Draw(mask_po)
    # Wire hanger loop
    d_po.rounded_rectangle([(75, 2), (380, 120)], radius=30, fill=255)
    d_po.rounded_rectangle([(115, 20), (340, 78)], radius=20, fill=0)
    # PCB main body
    d_po.rectangle([(0, 76), (w_po, h_po)], fill=255)

    # 2. Akai MPC Sample (akai_mpc_sample_blueprint_topdown_te_style.jpg)
    # Bbox: (228, 110, 825, 748) -> (597 x 638)
    im_mpc = Image.open(os.path.join(ref_dir, "akai_mpc_sample_blueprint_topdown_te_style.jpg"))
    crop_mpc = im_mpc.crop((228, 110, 825, 748)).convert("RGB")
    w_mpc, h_mpc = crop_mpc.size
    mask_mpc = Image.new("L", (w_mpc, h_mpc), 0)
    d_mpc = ImageDraw.Draw(mask_mpc)
    d_mpc.rounded_rectangle([(0, 0), (w_mpc, h_mpc)], radius=18, fill=255)

    # 3. Roland SP-404MK2 (roland_sp404mk2_blueprint_te_style.jpg)
    # Bbox: (178, 210, 672, 1128) -> (494 x 918)
    im_sp = Image.open(os.path.join(ref_dir, "roland_sp404mk2_blueprint_te_style.jpg"))
    crop_sp = im_sp.crop((178, 210, 672, 1128)).convert("RGB")
    w_sp, h_sp = crop_sp.size
    mask_sp = Image.new("L", (w_sp, h_sp), 0)
    d_sp = ImageDraw.Draw(mask_sp)
    d_sp.rounded_rectangle([(0, 0), (w_sp, h_sp)], radius=18, fill=255)

    # 4. NI Maschine MK3 (maschine_blueprint_te_style_from_user_photo.jpg)
    # Bbox: (137, 200, 885, 857) -> (748 x 657)
    im_mas = Image.open(os.path.join(ref_dir, "maschine_blueprint_te_style_from_user_photo.jpg"))
    crop_mas = im_mas.crop((137, 200, 885, 857)).convert("RGB")
    w_mas, h_mas = crop_mas.size
    mask_mas = Image.new("L", (w_mas, h_mas), 255)

    # 5. Teenage Engineering EP-133 K.O. II (ep133_blueprint_te_style.jpg)
    # Bbox: (67, 55, 827, 1075) -> (760 x 1020)
    im_ep = Image.open(os.path.join(ref_dir, "ep133_blueprint_te_style.jpg"))
    crop_ep = im_ep.crop((67, 55, 827, 1075)).convert("RGB")
    w_ep, h_ep = crop_ep.size
    arr_ep = np.array(crop_ep)
    bg_ep = np.array([241, 241, 241])
    ep_mask_arr = np.zeros((h_ep, w_ep), dtype=np.uint8)
    ep_mask_arr[55:, :] = 255
    for y in range(55):
        diff = np.linalg.norm(arr_ep[y, :, :3].astype(int) - bg_ep, axis=1)
        ep_mask_arr[y, diff > 15] = 255
    mask_ep = Image.fromarray(ep_mask_arr)

    # Build Bone variants (transparent background outside chassis, solid contour)
    def make_bone_variant(crop_im, mask_im, contour_type="rect", radius=18):
        rgba = crop_im.convert("RGBA")
        rgba.putalpha(mask_im)
        draw = ImageDraw.Draw(rgba)
        w, h = rgba.size
        outline_col = (20, 20, 24, 255)
        if contour_type == "rounded":
            draw.rounded_rectangle([(1, 1), (w - 2, h - 2)], radius=radius, outline=outline_col, width=2)
        elif contour_type == "rect":
            draw.rectangle([(0, 0), (w - 1, h - 1)], outline=outline_col, width=2)
        elif contour_type == "po33":
            draw.rectangle([(0, 76), (w - 1, h - 1)], outline=outline_col, width=2)
        elif contour_type == "ep133":
            draw.rectangle([(0, 55), (w - 1, h - 1)], outline=outline_col, width=2)
        return rgba

    bone_po = make_bone_variant(crop_po, mask_po, "po33")
    bone_mpc = make_bone_variant(crop_mpc, mask_mpc, "rounded", radius=18)
    bone_sp = make_bone_variant(crop_sp, mask_sp, "rounded", radius=18)
    bone_mas = make_bone_variant(crop_mas, mask_mas, "rect")
    bone_ep = make_bone_variant(crop_ep, mask_ep, "ep133")

    # Build Dark variants (crisp light linework, dark chassis, preserved accents, transparent background)
    def make_dark_variant(crop_im, mask_im, chassis_rgb, contour_type="rect", radius=18, accent_rgb=None):
        rgb = np.array(crop_im, dtype=float)
        mask = np.array(mask_im, dtype=float) / 255.0
        
        lum = 0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]
        max_c = rgb.max(axis=2)
        min_c = rgb.min(axis=2)
        sat = np.where(max_c > 0, (max_c - min_c) / np.maximum(max_c, 1), 0)
        
        # Color accents (orange, red, blue, green, amber)
        is_accent = (sat > 0.22) & (max_c > 65)
        
        # Monochromatic line mapping:
        norm_dark = np.clip(1.0 - (lum / 240.0), 0.0, 1.0)
        line_factor = np.power(norm_dark, 0.78)
        
        line_rgb = (235, 238, 245)
        out_rgb = np.zeros_like(rgb)
        for c in range(3):
            bg_v = chassis_rgb[c]
            ln_v = line_rgb[c]
            gray_mapped = bg_v + line_factor * (ln_v - bg_v)
            out_rgb[:, :, c] = np.where(is_accent, np.clip(rgb[:, :, c] * 1.05, 0, 255), gray_mapped)
            
        out_arr = np.dstack([out_rgb, mask * 255.0]).astype(np.uint8)
        dark_im = Image.fromarray(out_arr)
        
        draw = ImageDraw.Draw(dark_im)
        w, h = dark_im.size
        outline_col = (180, 185, 200, 255)
        if contour_type == "rounded":
            draw.rounded_rectangle([(1, 1), (w - 2, h - 2)], radius=radius, outline=outline_col, width=2)
        elif contour_type == "rect":
            draw.rectangle([(0, 0), (w - 1, h - 1)], outline=outline_col, width=2)
        elif contour_type == "po33":
            draw.rectangle([(0, 76), (w - 1, h - 1)], outline=outline_col, width=2)
        elif contour_type == "ep133":
            draw.rectangle([(0, 55), (w - 1, h - 1)], outline=outline_col, width=2)
            
        return dark_im

    return {
        "raw": {
            "po33": (crop_po, mask_po, "po33", 18),
            "mpc": (crop_mpc, mask_mpc, "rounded", 18),
            "sp404": (crop_sp, mask_sp, "rounded", 18),
            "maschine": (crop_mas, mask_mas, "rect", 18),
            "ep133": (crop_ep, mask_ep, "ep133", 18)
        },
        "bone": {
            "po33": bone_po,
            "mpc": bone_mpc,
            "sp404": bone_sp,
            "maschine": bone_mas,
            "ep133": bone_ep
        },
        "make_dark": make_dark_variant
    }

def build_all_theme_banners():
    ref_dir = "/Users/ivan/Downloads/BEATMAKER HARDWARES REF"
    scratch_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/scratch"
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    brain_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(brain_dir, exist_ok=True)

    print("Extracting clean devices and preparing dark/bone engines...")
    data = extract_and_prepare_all_devices(ref_dir, scratch_dir)

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
            "chassis_rgb": (16, 18, 24),
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
            "chassis_rgb": (12, 15, 22),
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
            "chassis_rgb": (24, 25, 30),
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
            "chassis_rgb": (12, 13, 18),
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
            "chassis_rgb": (18, 20, 25),
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
            "chassis_rgb": (240, 239, 235),
            "is_dark": False,
            "filename": "banner_blueprint_edition.jpg"
        }
    ]

    W, H = 2560, 1440
    margin = 50

    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"
    font_title = ImageFont.truetype(ttc, 44, index=1)
    font_system = ImageFont.truetype(ttc, 22, index=10)
    font_ref = ImageFont.truetype(ttc, 16, index=7)
    font_st_label = ImageFont.truetype(ttc, 22, index=1)
    font_footer_spec = ImageFont.truetype(ttc, 20, index=1)
    font_footer_stations = ImageFont.truetype(ttc, 18, index=10)
    font_footer_arch = ImageFont.truetype(ttc, 15, index=7)
    font_badge = ImageFont.truetype(ttc, 16, index=10)

    # Balanced station positions with 120+ px gaps (ZERO collisions, ZERO overlaps)
    stations_def = [
        {"name": "01 / pocket operator", "key": "po33", "target_w": 309, "target_h": 680, "cx": 224},
        {"name": "02 / akai mpc", "key": "mpc", "target_w": 402, "target_h": 430, "cx": 701},
        {"name": "03 / roland sp-404mk2", "key": "sp404", "target_w": 366, "target_h": 680, "cx": 1206},
        {"name": "04 / ni maschine", "key": "maschine", "target_w": 432, "target_h": 380, "cx": 1726},
        {"name": "05 / ep-133 k.o. ii", "key": "ep133", "target_w": 425, "target_h": 570, "cx": 2275}
    ]

    hardware_base_y = 1200
    label_y = margin + 185

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

        # 1. Centered Prominent Header
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

        # 2. Hardware Stations (No collisions, zero boxes)
        for st in stations_def:
            cx = st["cx"]
            
            # Label
            bbox_l = font_st_label.getbbox(st["name"])
            tw = bbox_l[2] - bbox_l[0]
            draw.text((cx - tw // 2, label_y), st["name"], fill=th["text_main"], font=font_st_label)
            draw.line([(cx - 20, label_y - 8), (cx + 20, label_y - 8)], fill=th["accent"], width=2)

            # Prepare Device
            k = st["key"]
            if th["is_dark"]:
                crop_im, mask_im, ctype, rad = data["raw"][k]
                dev_img = data["make_dark"](crop_im, mask_im, th["chassis_rgb"], ctype, rad)
            else:
                dev_img = data["bone"][k]

            scaled = dev_img.resize((st["target_w"], st["target_h"]), Image.Resampling.LANCZOS)
            
            pos_x = cx - st["target_w"] // 2
            pos_y = hardware_base_y - st["target_h"]
            
            # Contact Shadow
            sh_w, sh_h = int(st["target_w"] * 0.95), 24
            shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow)
            alpha_val = 140 if th["is_dark"] else 40
            sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, alpha_val))
            shadow = shadow.filter(ImageFilter.GaussianBlur(8))
            banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 12), shadow)
            
            # Paste Device (with transparent alpha mask)
            banner.paste(scaled, (pos_x, pos_y), scaled)
            
            # Technical crosshair
            draw.line([(cx - 20, hardware_base_y + 18), (cx + 20, hardware_base_y + 18)], fill=cross_col, width=1)
            draw.line([(cx, hardware_base_y + 10), (cx, hardware_base_y + 26)], fill=cross_col, width=1)

        # 3. Footer Serigraphy
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
            shutil.copy2(out_p, os.path.join(out_dir, "te_universal_beatmaker_banner.jpg"))
            shutil.copy2(out_p, os.path.join(out_dir, "banner_variant_01_mpc_sample.jpg"))
            shutil.copy2(out_p, os.path.join(brain_dir, "te_universal_beatmaker_banner.jpg"))
            banner.save(os.path.join(out_dir, "te_universal_beatmaker_banner_preview.png"), format="PNG")
            banner.save(os.path.join(brain_dir, "te_universal_beatmaker_banner_preview.png"), format="PNG")
        elif th["id"] == "makerlicious-bone":
            shutil.copy2(out_p, os.path.join(out_dir, "te_universal_beatmaker_banner_bone.jpg"))
            shutil.copy2(out_p, os.path.join(brain_dir, "banner_blueprint_edition.jpg"))
            banner.save(os.path.join(out_dir, "te_universal_beatmaker_blueprint_edition.png"), format="PNG")
            banner.save(os.path.join(brain_dir, "te_universal_beatmaker_blueprint_edition.png"), format="PNG")

    print("\nAll 6 theme banners created and synchronized successfully!")

if __name__ == "__main__":
    build_all_theme_banners()
