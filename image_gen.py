import io
from PIL import Image, ImageDraw, ImageFont, ImageOps

def get_font(size):
    try:
        # Tries to use Arial, fallback to default if not found
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        return ImageFont.load_default()

def create_circular_avatar(avatar_bytes, size=150):
    if not avatar_bytes:
        # Create a default grey avatar if none provided
        img = Image.new('RGB', (size, size), color=(100, 100, 100))
    else:
        img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    
    # Create a circular mask
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    
    output = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
    output.putalpha(mask)
    
    # Add a white border
    border_size = 6
    final_size = size + border_size * 2
    border_img = Image.new('RGBA', (final_size, final_size), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(border_img)
    b_draw.ellipse((0, 0, final_size, final_size), fill=(255, 255, 255, 255))
    border_img.paste(output, (border_size, border_size), output)
    
    return border_img

def generate_leaderboard(guild_name, iteration_text, top_users):
    """
    top_users is a list of dicts up to 6 items:
    [{'name': 'user1', 'score': 100, 'avatar_bytes': b'...'}, ...]
    """
    # Open the provided background
    try:
        base = Image.open("background.png").convert("RGBA")
    except Exception:
        # Fallback to a solid dark grey if background.png is missing
        base = Image.new("RGBA", (1280, 960), (30, 30, 30, 255))

    draw = ImageDraw.Draw(base)
    width, height = base.size
    
    # Fonts
    title_font = get_font(48)
    subtitle_font = get_font(36)
    name_font = get_font(28)
    score_font = get_font(40)
    rank_font = get_font(32)

    # Colors perfectly matched to your reference
    gold = (218, 165, 32, 255)
    silver = (192, 192, 192, 255)
    bronze = (205, 127, 50, 255)
    light_blue = (135, 206, 250, 255)

    # Draw Titles
    title_text = f"MOST SHAMEFUL PEOPLE OF {guild_name.upper()}"
    t_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    t_w = t_bbox[2] - t_bbox[0]
    draw.text(((width - t_w) / 2, 50), title_text, font=title_font, fill=light_blue)

    sub_text = iteration_text.upper()
    s_bbox = draw.textbbox((0, 0), sub_text, font=subtitle_font)
    s_w = s_bbox[2] - s_bbox[0]
    draw.text(((width - s_w) / 2, 110), sub_text, font=subtitle_font, fill=light_blue)

    # Podium Positions Setup
    # 1st place: center, 2nd place: left, 3rd place: right
    podium_positions = [
        # (x_center, y_bottom, width, height, color, rank_text)
        (width // 2, 700, 200, 350, gold, "1st"),
        (width // 2 - 250, 700, 200, 250, silver, "2nd"),
        (width // 2 + 250, 700, 200, 200, bronze, "3rd")
    ]

    for i in range(min(3, len(top_users))):
        user = top_users[i]
        x_center, y_bottom, p_w, p_h, color, rank_str = podium_positions[i]
        
        # Draw block (rounded rectangle)
        x_left = x_center - p_w // 2
        y_top = y_bottom - p_h
        draw.rounded_rectangle([x_left, y_top, x_left + p_w, y_bottom], radius=15, fill=color)
        
        # Draw text inside block
        score_text = f"{user['score']}\npts"
        draw.multiline_text((x_center, y_top + p_h//2 - 20), score_text, font=score_font, fill=(255, 255, 255, 255), anchor="mm", align="center")
        
        # Rank text at bottom of block
        draw.text((x_center, y_bottom + 30), rank_str, font=rank_font, fill=(200, 200, 200, 255), anchor="mm")

        # Draw username above block
        name_y = y_top - 30
        draw.text((x_center, name_y), user['name'], font=name_font, fill=light_blue, anchor="mm")

        # Draw circular avatar above username
        avatar_img = create_circular_avatar(user['avatar_bytes'], size=140)
        a_w, a_h = avatar_img.size
        base.paste(avatar_img, (x_center - a_w//2, name_y - 20 - a_h), avatar_img)

    # Bottom row setup (4th, 5th, 6th)
    bottom_y = 850
    spacing = 300
    start_x = width // 2 - spacing
    for i in range(3, min(6, len(top_users))):
        user = top_users[i]
        x_pos = start_x + (i - 3) * spacing
        
        rank_str = f"{i+1}th:"
        draw.text((x_pos - 90, bottom_y), rank_str, font=name_font, fill=light_blue, anchor="mm")
        
        # Small avatar
        avatar_img = create_circular_avatar(user['avatar_bytes'], size=70)
        a_w, a_h = avatar_img.size
        base.paste(avatar_img, (x_pos - 40, bottom_y - a_h//2), avatar_img)
        
        # Name and score
        draw.text((x_pos + 45, bottom_y - 15), user['name'], font=name_font, fill=light_blue, anchor="lm")
        draw.text((x_pos + 45, bottom_y + 15), f"{user['score']} pts", font=name_font, fill=(255, 255, 255, 255), anchor="lm")

    # Save to bytes buffer
    out_bytes = io.BytesIO()
    base.save(out_bytes, format='PNG')
    out_bytes.seek(0)
    return out_bytes
