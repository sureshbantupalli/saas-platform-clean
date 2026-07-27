import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"

def extract_foreign_keys(file_path):
    """Extract ForeignKey and relationship references from models"""
    relations = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            # Find ForeignKey references
            fk_pattern = r"ForeignKey\s*\(\s*['\"]?(\w+)['\"]?"
            matches = re.findall(fk_pattern, content)
            relations.extend(matches)
            
            # Find ManyToMany references
            m2m_pattern = r"ManyToManyField\s*\(\s*['\"]?(\w+)['\"]?"
            matches = re.findall(m2m_pattern, content)
            relations.extend(matches)
    except:
        pass
    return relations

apps_to_analyze = [
    'core', 'accounts', 'memberships', 'assessments', 'platform_sessions',
    'lifecycles', 'monitoring', 'tenants', 'authority', 'dashboard',
    'bookings', 'payments', 'attendance', 'sessions', 'communications',
    'analytics', 'actions', 'audit', 'verticals', 'catalog', 'enrollments',
    'activity', 'expenses', 'payouts', 'documents', 'reporting', 'renewals',
    'engagement', 'revenue', 'intake'
]

settings_apps = ['roles', 'vocabulary', 'branding', 'whatsapp']

# Analyze model dependencies
model_deps = {}
for app_name in apps_to_analyze:
    app_path = APPS_DIR / app_name
    models_file = app_path / "models.py"
    if models_file.exists():
        rels = extract_foreign_keys(models_file)
        if rels:
            model_deps[app_name] = rels

for app_name in settings_apps:
    app_path = APPS_DIR / "settings" / app_name
    models_file = app_path / "models.py"
    if models_file.exists():
        rels = extract_foreign_keys(models_file)
        if rels:
            model_deps[f"settings.{app_name}"] = rels

for app_path in [BASE_DIR / "members", BASE_DIR / "crm", BASE_DIR / "platform_core"]:
    if app_path.exists():
        models_file = app_path / "models.py"
        if models_file.exists():
            rels = extract_foreign_keys(models_file)
            if rels:
                model_deps[app_path.name] = rels

with open('model_dependencies.txt', 'w', encoding='utf-8') as f:
    f.write("=" * 100 + "\n")
    f.write("MODEL DEPENDENCIES (ForeignKey & M2M relationships)\n")
    f.write("=" * 100 + "\n\n")
    
    if model_deps:
        for app_name in sorted(model_deps.keys()):
            f.write(f"{app_name}:\n")
            for rel in model_deps[app_name]:
                f.write(f"  - {rel}\n")
            f.write("\n")
    else:
        f.write("No model relationships detected.\n")

print("Model dependencies analysis written to model_dependencies.txt")
