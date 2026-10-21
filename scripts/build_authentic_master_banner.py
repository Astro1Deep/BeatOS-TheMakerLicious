#!/usr/bin/env python3
"""
Build 100% Authentic, High-Definition Master Banners (4K UHD 3840x2160 @ 300 DPI)
for BeatOS — The MakerLicious.

Sheets:
  Sheet 01: 02 / akai mpc -> Akai MPC Sample (AC50)
  Sheet 02: 02 / akai mpc -> Akai MPC One (Cobalt G2)
  Sheet 03: 02 / akai mpc -> Akai MPC Live III Retro

Modes:
  - Bone White (TE technical drafting paper #f5f5f7)
  - Dark Flagship (Obsidian PCB #0d0f14)

Zero redundant 'The system' text, clean & direct station labels matching across ALL sheets,
unified specifications, corner registration crosses, and hairline millimeter grid.
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def render_banner(mpc_key, sheet_num, is_dark=False):
    W, H = 3840, 2160
    
    if is_dark:
        bg_color = (13, 15, 20)           # #0d0f14 Obsidian PCB
        grid_color = (23, 27, 36)         # #171b24
        major_grid = (34, 40, 54)         # #222836
        border_color = (43, 50, 66)       # #2b3242
        reg_color = (90, 100, 120)
        text_primary = (245, 245, 247)    # Crisp Swiss Chalk White
        text_muted = (140, 147, 163)      # #8c93a3
        line_color = (37, 44, 59)
    else:
        bg_color = (245, 245, 247)         # Authentic drafting paper bone-white
        grid_color = (235, 235, 238)
        major_grid = (222, 222, 228)
        border_color = (200, 200, 208)
        reg_color = (140, 140, 148)
        text_primary = (18, 18, 20)       # Ink Black
        text_muted = (110, 110, 118)      # Drafting Gray
        line_color = (215, 215, 222)

    accent_orange = (255, 102, 0)         # #ff6600 Signature TE Arcade Orange

    banner = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(banner)

    # 1. Hairline millimeter grid
    for x in range(0, W, 60):
        c = major_grid if x % 300 == 0 else grid_color
        draw.line([(x, 0), (x, H)], fill=c, width=1)
    for y in range(0, H, 60):
        c = major_grid if y % 300 == 0 else grid_color
        draw.line([(0, y), (W, y)], fill=c, width=1)

    # Outer margin & technical boundary
    margin = 66
    draw.rectangle([(margin, margin), (W - margin, H - margin)], outline=border_color, width=2)

    # Corner registration crosses (+)
    reg = 16
    corners = [
        (margin + 18, margin + 18),
        (W - margin - 18, margin + 18),
        (margin + 18, H - margin - 18),
        (W - margin - 18, H - margin - 18)
    ]
    for cx, cy in corners:
        draw.line([(cx - reg, cy), (cx + reg, cy)], fill=reg_color, width=2)
        draw.line([(cx, cy - reg), (cx, cy + reg)], fill=reg_color, width=2)

    # Typography (Helvetica Neue)
    ttc = "/System/Library/Fonts/HelveticaNeue.ttc"
    font_main_title = ImageFont.truetype(ttc, 54, index=1)       # Bold
    font_subtitle   = ImageFont.truetype(ttc, 30, index=10)      # Medium
    font_ref        = ImageFont.truetype(ttc, 24, index=7)       # Light
    font_sheet      = ImageFont.truetype(ttc, 30, index=1)       # Bold
    font_st_label   = ImageFont.truetype(ttc, 33, index=1)       # Bold Station Label
    font_footer_spec = ImageFont.truetype(ttc, 30, index=1)      # Bold
    font_footer_st   = ImageFont.truetype(ttc, 27, index=10)     # Medium
    font_footer_arch = ImageFont.truetype(ttc, 22, index=7)      # Light
    font_badge       = ImageFont.truetype(ttc, 30, index=1)      # Bold Badge

    # 1. Header (Clean & Direct - No redundant 'The system')
    # Top-Left:
    draw.text((margin + 54, margin + 42), "BeatOS — The MakerLicious", fill=text_primary, font=font_main_title)
    draw.text((margin + 54, margin + 112), "[universal beatmaker station]", fill=accent_orange, font=font_subtitle)
    draw.text((margin + 54, margin + 158), "│ ref: mpc · sp-404 · pocket operator · maschine · ep-133 k.o. ii │", fill=text_muted, font=font_ref)

    # Top-Right Specification Block:
    tr_x = W - margin - 580
    draw.text((tr_x, margin + 52), "beatos labs // specification", fill=text_primary, font=font_subtitle)
    sheet_str = f"sheet {sheet_num:02d} of 03 // rev 2026"
    draw.text((tr_x, margin + 98), sheet_str, fill=accent_orange, font=font_sheet)

    # Divider line under header
    draw.line([(margin + 30, margin + 210), (W - margin - 30, margin + 210)], fill=line_color, width=2)

    # 2. Hardware Stations (Clean & Direct matching across all sheets):
    stations = [
        {"num": "01 / pocket operator", "key": "po33", "max_w": 570, "max_h": 1080},
        {"num": "02 / akai mpc",         "key": mpc_key, "max_w": 710, "max_h": 1100},
        {"num": "03 / roland sp-404mk2", "key": "sp404", "max_w": 650, "max_h": 1110},
        {"num": "04 / ni maschine",     "key": "maschine", "max_w": 710, "max_h": 1080},
        {"num": "05 / ep-133 k.o. ii",   "key": "ep133", "max_w": 660, "max_h": 1100}
    ]

    cuts_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"
    col_width = (W - 2 * margin - 120) / 5
    col_centers = [int(margin + 60 + (i + 0.5) * col_width) for i in range(5)]
    hardware_base_y = 1770
    label_y = margin + 260

    for i, st in enumerate(stations):
        cx = col_centers[i]
        
        # Station Label: Clean, centered, with orange accent tick
        bbox = font_st_label.getbbox(st["num"])
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, label_y), st["num"], fill=text_primary, font=font_st_label)
        draw.line([(cx - 24, label_y - 14), (cx + 24, label_y - 14)], fill=accent_orange, width=3)
        
        # Load official photograph cutout
        cut_p = f"{cuts_dir}/perfect_cut_{st['key']}.png"
        img = Image.open(cut_p).convert("RGBA")
        ow, oh = img.size
        scale = min(st["max_w"] / ow, st["max_h"] / oh)
        nw, nh = int(ow * scale), int(oh * scale)
        scaled = img.resize((nw, nh), Image.Resampling.LANCZOS)
        
        pos_x = cx - nw // 2
        pos_y = hardware_base_y - nh
        
        # Realistic contact shadow
        sh_w, sh_h = int(nw * 0.94), 42
        shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse([(0, 0), (sh_w, sh_h)], fill=(0, 0, 0, 90 if not is_dark else 140))
        shadow = shadow.filter(ImageFilter.GaussianBlur(15))
        banner.paste(shadow, (cx - sh_w // 2, hardware_base_y - 20), shadow)
        
        # Crisp silhouette outline for high contrast definition
        sil_alpha = 75 if not is_dark else 100
        sil_col = (25, 25, 30, sil_alpha) if not is_dark else (240, 240, 245, sil_alpha)
        silhouette = Image.new("RGBA", (nw, nh), sil_col)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            banner.paste(silhouette, (pos_x + dx, pos_y + dy), scaled)
        
        # Paste hardware photograph
        banner.paste(scaled, (pos_x, pos_y), scaled)
        
        # Millimeter crosshair below unit
        draw.line([(cx - 36, hardware_base_y + 36), (cx + 36, hardware_base_y + 36)], fill=reg_color, width=1)
        draw.line([(cx, hardware_base_y + 24), (cx, hardware_base_y + 48)], fill=reg_color, width=1)

    # 3. Footer (Exact user specification)
    footer_y = H - margin - 195
    draw.line([(margin + 30, footer_y), (W - margin - 30, footer_y)], fill=line_color, width=2)

    spec_sheet = f"sheet {sheet_num:02d} of 03"
    draw.text((margin + 54, footer_y + 26), f"hardware guide specification // {spec_sheet}", fill=text_primary, font=font_footer_spec)
    stations_footer = "[A] pocket operator · [B] akai mpc · [C] roland sp-404mk2 · [D] ni maschine · [E] ep-133 k.o. ii"
    draw.text((margin + 54, footer_y + 72), stations_footer, fill=accent_orange, font=font_footer_st)
    draw.text((margin + 54, footer_y + 118), "16-pad unified fingerdrumming architecture", fill=text_muted, font=font_footer_arch)

    # Right technical spec badge
    badge_w = 690
    rx1 = W - margin - badge_w - 30
    draw.rectangle([(rx1, footer_y + 38), (W - margin - 30, footer_y + 110)], outline=accent_orange, width=2)
    draw.text((rx1 + 28, footer_y + 57), "[ 44.1 kHz / 16-BIT PCM · HARDWARE MATRIX ]", fill=accent_orange, font=font_badge)

    return banner

def main():
    out_dir = "/Users/ivan/Documents/mpc-sample-database/docs/assets/branding"
    ref_dir = "/Users/ivan/Downloads/BEATMAKER HARDWARES REF"
    brain_dir = "/Users/ivan/.gemini/antigravity/brain/8da64049-cb96-4c76-9d2a-381da30c7b9c"
    os.makedirs(out_dir, exist_ok=True)

    # -------------------------------------------------------------
    # 1. SHEET 01 (Akai MPC Sample)
    # -------------------------------------------------------------
    print("Generating Sheet 01 (Akai MPC Sample)...")
    # Bone White
    b1_bone = render_banner("mpc_sample", sheet_num=1, is_dark=False)
    b1_bone.save(f"{out_dir}/banner_variant_01_mpc_sample_bone.jpg", quality=98, dpi=(300, 300))
    b1_bone.save(f"{out_dir}/beatos_makerlicious_blueprint_banner_bone.jpg", quality=98, dpi=(300, 300))
    b1_bone.save(f"{out_dir}/banner_blueprint_edition.jpg", quality=98, dpi=(300, 300))
    b1_bone.save(f"{ref_dir}/beatos_makerlicious_blueprint_banner_bone.jpg", quality=98, dpi=(300, 300))
    b1_bone.save(f"{brain_dir}/beatos_makerlicious_blueprint_banner_bone.jpg", quality=98, dpi=(300, 300))

    # Dark Flagship
    b1_dark = render_banner("mpc_sample", sheet_num=1, is_dark=True)
    b1_dark.save(f"{out_dir}/banner_variant_01_mpc_sample.jpg", quality=98, dpi=(300, 300))
    b1_dark.save(f"{out_dir}/beatos_makerlicious_dark_blueprint_banner.jpg", quality=98, dpi=(300, 300))
    b1_dark.save(f"{out_dir}/te_universal_beatmaker_banner.jpg", quality=98, dpi=(300, 300))
    b1_dark.save(f"{out_dir}/te_universal_beatmaker_banner_preview.png")
    b1_dark.save(f"{ref_dir}/beatos_makerlicious_dark_blueprint_banner.jpg", quality=98, dpi=(300, 300))
    b1_dark.save(f"{brain_dir}/beatos_makerlicious_dark_blueprint_banner.jpg", quality=98, dpi=(300, 300))

    # -------------------------------------------------------------
    # 2. SHEET 02 (Akai MPC One Cobalt G2)
    # -------------------------------------------------------------
    print("Generating Sheet 02 (Akai MPC One)...")
    # Bone White
    b2_bone = render_banner("mpc_one", sheet_num=2, is_dark=False)
    b2_bone.save(f"{out_dir}/banner_variant_02_mpc_one.jpg", quality=98, dpi=(300, 300))
    b2_bone.save(f"{out_dir}/banner_variant_02_mpc_one_bone.jpg", quality=98, dpi=(300, 300))
    b2_bone.save(f"{brain_dir}/banner_variant_02_mpc_one.jpg", quality=98, dpi=(300, 300))

    # Dark
    b2_dark = render_banner("mpc_one", sheet_num=2, is_dark=True)
    b2_dark.save(f"{out_dir}/banner_variant_02_mpc_one_dark.jpg", quality=98, dpi=(300, 300))
    b2_dark.save(f"{brain_dir}/banner_variant_02_mpc_one_dark.jpg", quality=98, dpi=(300, 300))

    # -------------------------------------------------------------
    # 3. SHEET 03 (Akai MPC Live III Retro)
    # -------------------------------------------------------------
    print("Generating Sheet 03 (Akai MPC Live III Retro)...")
    # Bone White
    b3_bone = render_banner("mpc_live3", sheet_num=3, is_dark=False)
    b3_bone.save(f"{out_dir}/banner_variant_03_mpc_live3.jpg", quality=98, dpi=(300, 300))
    b3_bone.save(f"{out_dir}/banner_variant_03_mpc_live3_bone.jpg", quality=98, dpi=(300, 300))
    b3_bone.save(f"{brain_dir}/banner_variant_03_mpc_live3.jpg", quality=98, dpi=(300, 300))

    # Dark
    b3_dark = render_banner("mpc_live3", sheet_num=3, is_dark=True)
    b3_dark.save(f"{out_dir}/banner_variant_03_mpc_live3_dark.jpg", quality=98, dpi=(300, 300))
    b3_dark.save(f"{brain_dir}/banner_variant_03_mpc_live3_dark.jpg", quality=98, dpi=(300, 300))

    print("🎉 All 3 Sheets (Dark & Bone White, 3840x2160 4K UHD @ 300 DPI) generated with 100% data consistency!")

if __name__ == "__main__":
    main()
