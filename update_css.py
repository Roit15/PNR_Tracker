import re

file_path = '/Users/jangr/vibeCoding/PNR_Tracker/static/style.css'
with open(file_path, 'r') as f:
    content = f.read()

# 1. Replace the :root block completely
root_pattern = re.compile(r':root\s*\{[^}]+\}', re.MULTILINE)
new_root = """:root {
    /* Soft Slate Backgrounds */
    --bg-base: #0f172a;
    --bg-surface: #1e293b;
    --bg-card: #1e293b;
    --bg-card-hover: #334155;
    --bg-input: #0f172a;
    
    /* Softer Borders */
    --border: rgba(255, 255, 255, 0.08);
    --border-hover: rgba(255, 255, 255, 0.15);
    --border-focus: #6366f1;

    /* Off-white text to reduce glare */
    --text-primary: #e4e4e7;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;

    /* Calming Indigo Accent */
    --accent: #6366f1;
    --accent-hover: #818cf8;
    --accent-soft: rgba(99, 102, 241, 0.15);
    --accent-glow: rgba(99, 102, 241, 0.05);

    /* Status Colors - softer */
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --orange: #f97316;
    --purple: #8b5cf6;
    --cyan: #06b6d4;

    --radius: 12px;
    --radius-sm: 8px;
    --radius-xs: 6px;
    
    /* Soft drop shadows instead of neon glows */
    --shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    --shadow-lg: 0 10px 30px rgba(0, 0, 0, 0.3);
    
    --ease: cubic-bezier(0.4, 0, 0.2, 1);
}"""
content = root_pattern.sub(new_root, content, count=1)

# 2. Replace hardcoded accent colors (130, 81, 238) with new accent (99, 102, 241)
content = content.replace("130, 81, 238", "99, 102, 241")
content = content.replace("#8251EE", "var(--accent)")
content = content.replace("#9366F5", "var(--accent-hover)")

# 3. Soften the airlines showcase background (was very dark and high contrast)
content = content.replace(
    "background: linear-gradient(135deg, rgba(8, 18, 12, 0.7), rgba(12, 24, 16, 0.5));",
    "background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.5));"
)

# 4. Remove neon border colors in status badges (making them softer)
content = content.replace("border: 1px solid rgba(34, 197, 94, 0.25)", "border: 1px solid rgba(34, 197, 94, 0.15)")
content = content.replace("border: 1px solid rgba(34, 211, 238, 0.2)", "border: 1px solid rgba(34, 211, 238, 0.1)")
content = content.replace("border: 1px solid rgba(245, 158, 11, 0.25)", "border: 1px solid rgba(245, 158, 11, 0.15)")
content = content.replace("border: 1px solid rgba(249, 115, 22, 0.25)", "border: 1px solid rgba(249, 115, 22, 0.15)")
content = content.replace("border: 1px solid rgba(239, 68, 68, 0.25)", "border: 1px solid rgba(239, 68, 68, 0.15)")
content = content.replace("border: 1px solid rgba(90, 106, 133, 0.25)", "border: 1px solid rgba(90, 106, 133, 0.15)")
content = content.replace("border: 1px solid rgba(167, 139, 250, 0.2)", "border: 1px solid rgba(167, 139, 250, 0.1)")
content = content.replace("border: 1px solid rgba(148, 163, 184, 0.15)", "border: 1px solid rgba(148, 163, 184, 0.1)")

with open(file_path, 'w') as f:
    f.write(content)

print("CSS variables and hardcoded colors updated.")
