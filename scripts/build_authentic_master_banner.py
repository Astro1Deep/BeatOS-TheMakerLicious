#!/usr/bin/env python3
"""
Build 100% Authentic, Solid, High-Contrast Master Banners
Using official, real-world photographs from /Users/ivan/Downloads/BEATMAKER HARDWARES REF
Clean, homogeneous, 100% visible contours, zero eroded/transparent faceplates.
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def build_single_variant(mpc_key, mpc_name_label, mpc_footer_tag, sheet_num, out_filename, is_master=False):
    W, H = 2560, 1440
    bg_color = (245, 245, 247) # Authentic drafting paper bone-white

    banner = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(banner)

    # Hairline millimeter grid
    grid_color = (235, 235, 238)
    major_grid = (222, 222, 228)
    for x in range(0, W, 40):
        c = major_grid if x % 200 == 0 else grid_color
        draw.line([(x, 0), (x, H)], fill=c, width=1)
    for y in range(0, H, 40):
        c = major_grid if y % 200 == 0 else grid_color
        draw.line([(0, y), (W, y)], fill=c, width=1)

    # Outer margin & technical boundary
    margin = 44
    draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=(200, 200, 208), width=1)

    # Corner registration crosses (+)
    reg = 10
    corners = [
        (margin + 12, margin + 12),
        (W - margin - 12, margin + 12),
        (margin + 12, H - margin - 12),
        (W - margin - 12, H - margin - 12)
    ]
    for cx, cy in corners:
        draw.line([(cx - reg, cy), (cx + reg, cy)], fill=(140, 140, 148), width=1)
        draw.line([(cx, cy - reg), (cx, cy + reg)], fill=(140, 140, 148), width=1)

    # Typography
    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"

    font_main_title = ImageFont.truetype(ttc, 36, index=1)   # Bold
    font_system = ImageFont.truetype(ttc, 20, index=10)       # Medium
    font_ref = ImageFont.truetype(ttc, 16, index=7)          # Light / Mono
    font_sheet = ImageFont.truetype(ttc, 20, index=1)        # Bold Orange
    font_st_label = ImageFont.truetype(ttc, 22, index=1)     # Bold Station Label
    font_footer_spec = ImageFont.truetype(ttc, 20, index=1)  # Bold
    font_footer_stations = ImageFont.truetype(ttc, 18, index=10) # Medium
    font_footer_arch = ImageFont.truetype(ttc, 15, index=7)  # Light

    # 1. Header (Exact user specification)
    draw.text((margin + 36, margin + 28), "BeatOS — The MakerLicious", fill=(18, 18, 20), font=font_main_title)
    draw.text((margin + 36, margin + 74), "The system ★ [universal beatmaker station]", fill=(255, 102, 0), font=font_system)
    draw.text((margin + 36, margin + 104), "│ ref: mpc · sp-404 · pocket operator · maschine │", fill=(110, 110, 118), font=font_ref)

    draw.text((W - margin - 380, margin + 34), "beatos labs // specification", fill=(18, 18, 20), font=font_system)
    sheet_str = f"sheet {sheet_num:02d} of 03 // rev 2026" if not is_master else "sheet 01 of 01 // rev 2026"
    draw.text((W - margin - 380, margin + 64), sheet_str, fill=(255, 102, 0), font=font_sheet)

    # Divider line under header
    draw.line([(margin + 20, margin + 140), (W - margin - 20, margin + 140)], fill=(215, 215, 222), width=1)

    # 2. Hardware Stations in EXACT ORDER:
    # 01 / pocket operator
    # 02 / akai mpc
    # 03 / roland sp-404mk2
    # 04 / ni maschine
    # 05 / ep-133 k.o. ii
    stations = [
        {"num": "01 / pocket operator", "key": "po33", "max_w": 380, "max_h": 720},
        {"num": mpc_name_label, "key": mpc_key, "max_w": 470, "max_h": 730},
        {"num": "03 / roland sp-404mk2", "key": "sp404", "max_w": 430, "max_h": 740},
        {"num": "04 / ni maschine", "key": "maschine", "max_w": 470, "max_h": 720},
        {"num": "05 / ep-133 k.o. ii", "key": "ep133", "max_w": 440, "max_h": 730}
    ]

    cuts_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"
    col_width = (W - 2 * margin - 80) / 5
    col_centers = [int(margin + 40 + (i + 0.5) * col_width) for i in range(5)]
    hardware_base_y = 1180
    label_y = margin + 175

    for i, st in enumerate(stations):
        cx = col_centers[i]
        
        # Station Label (Clean and direct, NO subtitles)
        bbox = font_st_label.getbbox(st["num"])
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, label_y), st["num"], fill=(18, 18, 20), font=font_st_label)
        draw.line([(cx - 16, label_y - 10), (cx + 16, label_y - 10)], fill=(255, 102, 0), width=2)
        
        # Load the 100% SOLID photo cutout
        st_key = st["key"]
        cut_p = f"{cuts_dir}/perfect_cut_{st_key}.png"
        img = Image.open(cut_p).convert("RGBA")
        ow, oh = img.size
        scale = min(st["max_w"] / ow, st["max_h"] / oh)
        nw, nh = int(ow * scale), int(oh * scale)
        scaled = img.resize((nw, nh), Image.Resampling.LANCZOS)
        
        pos_x = cx - nw // 2
        pos_y = hardware_base_y - nh
        
        # 1. Realistic contact shadow under unit on baseline
        sh_w, sh_h = int(nw * 0.94), 28
        shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, 65))
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 14), shadow)
        
        # 2. Subtle crisp hairline contour around unit (makes edges 100% defined and visible against paper)
        silhouette = Image.new("RGBA", (nw, nh), (25, 25, 30, 85))
        banner.paste(silhouette, (pos_x - 1, pos_y), scaled)
        banner.paste(silhouette, (pos_x + 1, pos_y), scaled)
        banner.paste(silhouette, (pos_x, pos_y - 1), scaled)
        banner.paste(silhouette, (pos_x, pos_y + 1), scaled)
        
        # 3. Paste the 100% SOLID, HOMOGENEOUS hardware photograph
        banner.paste(scaled, (pos_x, pos_y), scaled)
        
        # Millimeter calibration crosshair under station
        draw.line([(cx - 24, hardware_base_y + 24), (cx + 24, hardware_base_y + 24)], fill=(180, 180, 188), width=1)
        draw.line([(cx, hardware_base_y + 16), (cx, hardware_base_y + 32)], fill=(180, 180, 188), width=1)

    # 3. Footer (Exact user specification)
    footer_y = H - margin - 130
    draw.line([(margin + 20, footer_y), (W - margin - 20, footer_y)], fill=(215, 215, 222), width=1)

    spec_sheet = "sheet 01 of 01" if is_master else f"sheet {sheet_num:02d} of 03"
    draw.text((margin + 36, footer_y + 18), f"hardware guide specification // {spec_sheet}", fill=(18, 18, 20), font=font_footer_spec)
    stations_footer = f"[A] pocket operator · [B] {mpc_footer_tag} · [C] roland sp-404mk2 · [D] ni maschine · [E] ep-133 k.o. ii"
    draw.text((margin + 36, footer_y + 48), stations_footer, fill=(255, 102, 0), font=font_footer_stations)
    draw.text((margin + 36, footer_y + 78), "16-pad unified fingerdrumming architecture", fill=(110, 110, 118), font=font_footer_arch)

    # Right tech spec badge
    rx1 = W - margin - 460
    draw.rectangle([(rx1, footer_y + 25), (W - margin - 36, footer_y + 72)], outline=(255, 102, 0), width=1)
    draw.text((rx1 + 18, footer_y + 38), "[ 44.1 kHz / 16-BIT PCM · HARDWARE MATRIX ]", fill=(255, 102, 0), font=font_system)

    # Save output
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{out_filename}"
    banner.save(out_path, quality=98)
    
    if is_master:
        banner.save(f"{out_dir}/te_universal_beatmaker_banner.jpg", quality=98)
        banner.save(f"{out_dir}/te_universal_beatmaker_banner_preview.png")
        banner.save(f"{out_dir}/banner_bone_glitch_edition.jpg", quality=98)
        banner.save(f"{out_dir}/te_universal_beatmaker_banner_bone_glitch.png")
        banner.save("/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/te_universal_beatmaker_banner_preview.png")
        banner.save("/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/te_universal_beatmaker_banner.jpg", quality=98)
        banner.save("/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c/banner_bone_glitch_edition.jpg", quality=98)

    print(f"✅ Generated authentic solid banner: {out_filename}")

def main():
    # 1. Master & Variant 1: Akai MPC Sample
    build_single_variant(
        mpc_key="mpc_sample",
        mpc_name_label="02 / akai mpc",
        mpc_footer_tag="akai mpc",
        sheet_num=1,
        out_filename="banner_variant_01_mpc_sample.jpg",
        is_master=True
    )

    # 2. Variant 2: Akai MPC One (Cobalt G2)
    build_single_variant(
        mpc_key="mpc_one",
        mpc_name_label="02 / akai mpc",
        mpc_footer_tag="akai mpc",
        sheet_num=2,
        out_filename="banner_variant_02_mpc_one.jpg",
        is_master=False
    )

    # 3. Variant 3: Akai MPC Live III Retro
    build_single_variant(
        mpc_key="mpc_live3",
        mpc_name_label="02 / akai mpc",
        mpc_footer_tag="akai mpc",
        sheet_num=3,
        out_filename="banner_variant_03_mpc_live3.jpg",
        is_master=False
    )

if __name__ == "__main__":
    main()
