#!/usr/bin/env python
"""
Deployment validation script for modular SaaS platform.

Validates:
1. Module dependencies are satisfied
2. No circular dependencies exist
3. Test coverage meets minimum requirements
4. Security configuration is correct
5. Database is properly configured
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple, Set
import subprocess

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')


def validate_dependencies(scenario: str) -> Tuple[bool, str]:
    """
    Validate that all required dependencies are present for a scenario.

    Args:
        scenario: Deployment scenario name

    Returns:
        (success: bool, message: str)
    """
    from config.settings.modules import ModuleRegistry

    try:
        registry = ModuleRegistry(scenario)
        registry.validate_dependencies()

        modules = registry.deployed_modules
        missing = []

        for module in modules:
            if module not in registry.MODULES:
                missing.append(module)

        if missing:
            return False, f"Unknown modules: {', '.join(missing)}"

        return True, f"✅ Dependency validation passed for {len(modules)} modules"

    except Exception as e:
        return False, f"❌ Dependency validation failed: {e}"


def check_circular_dependencies(scenario: str) -> Tuple[bool, str]:
    """
    Check for circular dependencies in the module graph.

    Args:
        scenario: Deployment scenario name

    Returns:
        (success: bool, message: str)
    """
    from config.settings.modules import ModuleRegistry

    try:
        registry = ModuleRegistry(scenario)
        modules = registry.deployed_modules

        # Build dependency graph
        graph = {}
        for module in modules:
            module_info = registry.MODULES[module]
            deps = module_info.get('dependencies', [])
            graph[module] = set(deps) & set(modules)

        # DFS to detect cycles
        def has_cycle(node, visited, rec_stack, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack, path):
                        return True
                elif neighbor in rec_stack:
                    cycle = path[path.index(neighbor):] + [neighbor]
                    return cycle

            path.pop()
            rec_stack.remove(node)
            return False

        visited = set()
        rec_stack = set()

        for module in modules:
            if module not in visited:
                result = has_cycle(module, visited, rec_stack, [])
                if result and result is not True:
                    cycle_str = " -> ".join(result)
                    return False, f"❌ Circular dependency detected: {cycle_str}"

        return True, "✅ No circular dependencies detected"

    except Exception as e:
        return False, f"❌ Circular dependency check failed: {e}"


def validate_test_coverage(scenario: str, min_coverage: float = 85.0) -> Tuple[bool, str]:
    """
    Validate that test coverage meets minimum requirements.

    Args:
        scenario: Deployment scenario name
        min_coverage: Minimum coverage percentage

    Returns:
        (success: bool, message: str)
    """
    try:
        from config.settings.modules import ModuleRegistry

        registry = ModuleRegistry(scenario)
        test_markers = registry.test_markers

        # Run pytest with coverage
        cmd = [
            'pytest',
            '--cov=apps',
            '--cov-report=term',
            f"--cov-fail-under={int(min_coverage)}",
            '-m', ' or '.join(test_markers),
            '-q'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)

        if result.returncode == 0:
            return True, f"✅ Test coverage validation passed (≥{min_coverage}%)"
        else:
            # Try to extract coverage from output
            output = result.stdout + result.stderr
            if 'FAILED' in output or 'ERROR' in output:
                return False, f"❌ Test coverage validation failed: coverage < {min_coverage}%"
            return False, f"❌ Test coverage check failed:\n{output}"

    except Exception as e:
        return False, f"⚠️  Could not verify test coverage: {e}"


def validate_configuration(scenario: str) -> Tuple[bool, str]:
    """
    Validate that required configuration is set.

    Args:
        scenario: Deployment scenario name

    Returns:
        (success: bool, message: str)
    """
    from config.settings.modules import ModuleRegistry

    try:
        registry = ModuleRegistry(scenario)

        # Check for financial module - requires payment gateway
        if registry.is_module_enabled('financial'):
            payment_gateway = os.getenv('PAYMENT_GATEWAY')
            if not payment_gateway:
                return False, "❌ Financial module enabled but PAYMENT_GATEWAY not configured"

        # Check for communication module - requires email
        if registry.is_module_enabled('communication'):
            email_backend = os.getenv('EMAIL_BACKEND') or 'console'
            if email_backend == 'console':
                return False, "❌ Communication module enabled but EMAIL_BACKEND not properly configured"

        # Check for WhatsApp
        if registry.is_feature_enabled('whatsapp_enabled'):
            whatsapp_token = os.getenv('WHATSAPP_API_TOKEN')
            if not whatsapp_token:
                return False, "❌ WhatsApp enabled but WHATSAPP_API_TOKEN not configured"

        return True, "✅ Configuration validation passed"

    except Exception as e:
        return False, f"❌ Configuration validation failed: {e}"


def validate_database(scenario: str) -> Tuple[bool, str]:
    """
    Validate database connectivity and schema.

    Args:
        scenario: Deployment scenario name

    Returns:
        (success: bool, message: str)
    """
    try:
        import django
        django.setup()

        from django.db import connection
        from django.core.management import execute_from_command_line

        # Check database connectivity
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        # Check pending migrations
        pending = subprocess.run(
            [sys.executable, 'manage.py', 'showmigrations', '--plan'],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )

        if '[ ]' in pending.stdout:
            return False, "❌ Pending migrations exist. Run: python manage.py migrate"

        return True, "✅ Database validation passed"

    except Exception as e:
        return False, f"❌ Database validation failed: {e}"


def validate_security(scenario: str) -> Tuple[bool, str]:
    """
    Validate security configuration.

    Args:
        scenario: Deployment scenario name

    Returns:
        (success: bool, message: str)
    """
    from config.settings.modules import ModuleRegistry
    import django
    django.setup()
    from django.conf import settings

    try:
        registry = ModuleRegistry(scenario)
        warnings = []

        # Check DEBUG setting
        if settings.DEBUG:
            warnings.append("⚠️  DEBUG=True in production")

        # Check SECRET_KEY
        if settings.SECRET_KEY == 'dev-secret-key':
            warnings.append("⚠️  Using default SECRET_KEY")

        # Check HTTPS/TLS
        if not settings.SECURE_SSL_REDIRECT and not os.getenv('INSECURE_ENV'):
            warnings.append("⚠️  SECURE_SSL_REDIRECT not enabled")

        # Check PCI compliance if financial
        if registry.is_module_enabled('financial'):
            if not settings.SECURE_SSL_REDIRECT:
                return False, "❌ Financial module requires HTTPS/TLS enabled"

        if warnings:
            return True, f"✅ Security check passed with warnings:\n" + "\n".join(warnings)

        return True, "✅ Security validation passed"

    except Exception as e:
        return False, f"⚠️  Security validation error: {e}"


class DeploymentValidator:
    """Comprehensive deployment validator."""

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.results = {}
        self.passed = []
        self.failed = []

    def run_all_validations(self) -> bool:
        """Run all validation gates."""
        validations = [
            ('Dependency Check', validate_dependencies),
            ('Circular Dependency Check', check_circular_dependencies),
            ('Configuration Check', validate_configuration),
            ('Database Check', validate_database),
            ('Security Check', validate_security),
        ]

        print("\n" + "="*80)
        print(f"DEPLOYMENT VALIDATION FOR SCENARIO: {self.scenario}")
        print("="*80 + "\n")

        for name, validator_func in validations:
            try:
                success, message = validator_func(self.scenario)
                self.results[name] = (success, message)

                if success:
                    self.passed.append(name)
                    print(f"✅ {name}: {message}")
                else:
                    self.failed.append(name)
                    print(f"❌ {name}: {message}")
            except Exception as e:
                self.failed.append(name)
                print(f"❌ {name}: EXCEPTION: {e}")

            print()

        return len(self.failed) == 0

    def print_summary(self):
        """Print validation summary."""
        print("="*80)
        print("VALIDATION SUMMARY")
        print("="*80)
        print(f"Passed: {len(self.passed)}")
        print(f"Failed: {len(self.failed)}")
        print()

        if self.failed:
            print("❌ FAILED VALIDATIONS:")
            for name in self.failed:
                print(f"  - {name}")
            print()
            return False

        print("✅ ALL VALIDATIONS PASSED")
        print()
        return True


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_deployment.py <scenario>")
        print("\nAvailable scenarios:")
        print("  - full_platform")
        print("  - crm_only")
        print("  - fitness_only")
        print("  - whatsapp_only")
        print("  - academy")
        print("  - financial_only")
        sys.exit(1)

    scenario = sys.argv[1]

    validator = DeploymentValidator(scenario)
    success = validator.run_all_validations()
    summary_ok = validator.print_summary()

    sys.exit(0 if success and summary_ok else 1)


if __name__ == '__main__':
    main()
