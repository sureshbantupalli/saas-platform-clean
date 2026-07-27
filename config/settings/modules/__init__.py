"""
Module configuration system for modular Django deployment.

This module provides the registry and configuration management for
deploying different combinations of features to different tenants.
"""

from pathlib import Path
import os
from typing import List, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


class ModuleRegistry:
    """Central registry for all available modules and scenarios."""

    # Module definitions
    MODULES = {
        'core_infrastructure': {
            'name': 'Core Infrastructure',
            'required': True,
            'apps': ['core', 'tenants', 'accounts', 'authority'],
            'optional_features': ['audit'],
            'dependencies': [],
            'database_tables': [
                'core_*', 'tenants_*', 'accounts_*', 'authority_*', 'audit_*'
            ],
            'test_coverage_min': 90,
            'test_markers': ['critical', 'isolation', 'auth'],
        },
        'user_management': {
            'name': 'User Management',
            'required': False,
            'apps': ['memberships', 'platform_sessions', 'activity', 'lifecycles'],
            'optional_features': ['activity', 'lifecycles', 'platform_sessions'],
            'dependencies': ['core_infrastructure'],
            'database_tables': [
                'memberships_*', 'platform_sessions_*', 'activity_*', 'lifecycles_*'
            ],
            'test_coverage_min': 85,
            'test_markers': ['module_user_management'],
        },
        'fitness_studio': {
            'name': 'Fitness Studio Operations',
            'required': False,
            'apps': ['sessions', 'bookings', 'attendance', 'verticals', 'catalog'],
            'optional_features': ['attendance', 'verticals', 'catalog'],
            'dependencies': ['core_infrastructure', 'user_management'],
            'database_tables': [
                'sessions_*', 'bookings_*', 'attendance_*', 'verticals_*', 'catalog_*'
            ],
            'test_coverage_min': 85,
            'test_markers': ['module_fitness_studio'],
        },
        'financial': {
            'name': 'Financial Management',
            'required': False,
            'apps': ['payments', 'revenue', 'expenses', 'payouts', 'renewals'],
            'optional_features': ['revenue', 'expenses', 'payouts', 'renewals'],
            'dependencies': ['core_infrastructure', 'user_management'],
            'database_tables': [
                'payments_*', 'revenue_*', 'expenses_*', 'payouts_*', 'renewals_*'
            ],
            'test_coverage_min': 90,
            'test_markers': ['module_financial'],
            'security_requirements': ['PCI-DSS', 'encryption'],
        },
        'communication': {
            'name': 'Communication & Engagement',
            'required': False,
            'apps': ['communications', 'settings.whatsapp', 'engagement', 'actions'],
            'optional_features': ['engagement', 'actions', 'settings.whatsapp'],
            'dependencies': ['core_infrastructure', 'user_management'],
            'database_tables': [
                'communications_*', 'engagement_*', 'actions_*', 'settings_whatsapp_*'
            ],
            'test_coverage_min': 85,
            'test_markers': ['module_communication'],
        },
        'analytics_reporting': {
            'name': 'Analytics & Reporting',
            'required': False,
            'apps': ['analytics', 'reporting', 'documents', 'dashboard'],
            'optional_features': ['analytics', 'reporting', 'documents', 'dashboard'],
            'dependencies': ['core_infrastructure'],
            'database_tables': [
                'analytics_*', 'reporting_*', 'documents_*', 'dashboard_*'
            ],
            'test_coverage_min': 80,
            'test_markers': ['module_analytics_reporting'],
        },
        'learning_assessment': {
            'name': 'Learning & Assessments',
            'required': False,
            'apps': ['assessments', 'intake', 'enrollments', 'branding_adapter'],
            'optional_features': ['intake', 'enrollments', 'branding_adapter'],
            'dependencies': ['core_infrastructure', 'user_management'],
            'database_tables': [
                'assessments_*', 'intake_*', 'enrollments_*'
            ],
            'test_coverage_min': 85,
            'test_markers': ['module_learning_assessment'],
        },
    }

    # Deployment scenarios
    SCENARIOS = {
        'full_platform': {
            'name': 'Full Platform',
            'description': 'Complete multi-tenant yoga studio platform',
            'modules': [
                'core_infrastructure',
                'user_management',
                'fitness_studio',
                'financial',
                'communication',
                'analytics_reporting',
                'learning_assessment',
            ],
            'estimated_deployment_time': '120-180m',
            'risk_level': 'MEDIUM',
            'test_count': 1000,
        },
        'crm_only': {
            'name': 'CRM-Only',
            'description': 'Customer relationship management without studio operations',
            'modules': [
                'core_infrastructure',
                'user_management',
                'communication',
            ],
            'estimated_deployment_time': '30-45m',
            'risk_level': 'LOW',
            'test_count': 150,
        },
        'whatsapp_only': {
            'name': 'WhatsApp & Communications Only',
            'description': 'WhatsApp messaging only, minimal user management',
            'modules': [
                'core_infrastructure',
                'communication',
            ],
            'estimated_deployment_time': '20-30m',
            'risk_level': 'VERY LOW',
            'test_count': 80,
        },
        'fitness_only': {
            'name': 'Fitness Studio',
            'description': 'Yoga studio with booking and payment, no CRM/analytics',
            'modules': [
                'core_infrastructure',
                'user_management',
                'fitness_studio',
                'financial',
            ],
            'estimated_deployment_time': '60-90m',
            'risk_level': 'MEDIUM-LOW',
            'test_count': 400,
        },
        'academy': {
            'name': 'Academy',
            'description': 'Online learning platform with assessments',
            'modules': [
                'core_infrastructure',
                'user_management',
                'learning_assessment',
                'communication',
            ],
            'estimated_deployment_time': '45-60m',
            'risk_level': 'LOW-MEDIUM',
            'test_count': 350,
        },
        'financial_only': {
            'name': 'Financial Only',
            'description': 'Standalone payment & financial reporting',
            'modules': [
                'core_infrastructure',
                'financial',
            ],
            'estimated_deployment_time': '25-40m',
            'risk_level': 'MEDIUM',
            'test_count': 180,
        },
    }

    def __init__(self, scenario: Optional[str] = None):
        """Initialize registry with a scenario."""
        self.scenario = scenario or os.getenv('DEPLOYMENT_SCENARIO', 'full_platform')

        if self.scenario not in self.SCENARIOS:
            raise ValueError(f"Unknown scenario: {self.scenario}")

        self.scenario_config = self.SCENARIOS[self.scenario]
        self.modules = self.scenario_config['modules']

    def get_installed_apps(self) -> List[str]:
        """Get list of Django apps to install for this scenario."""
        base_apps = [
            'django.contrib.admin',
            'django.contrib.auth',
            'django.contrib.contenttypes',
            'django.contrib.sessions',
            'django.contrib.messages',
            'django.contrib.staticfiles',
            'rest_framework',
        ]

        module_apps = []
        for module_name in self.modules:
            module_info = self.MODULES[module_name]
            for app_name in module_info['apps']:
                django_app = f'apps.{app_name}' if not '.' in app_name else app_name
                if django_app not in module_apps:
                    module_apps.append(django_app)

        # Add platform apps
        module_apps.extend(['members', 'crm', 'platform_core'])

        return base_apps + module_apps

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled in this scenario."""
        return module_name in self.modules

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature flag is enabled."""
        # Feature flags based on module availability
        feature_to_module = {
            'fitness_studio_enabled': 'fitness_studio',
            'bookings_enabled': 'fitness_studio',
            'sessions_enabled': 'fitness_studio',
            'payments_enabled': 'financial',
            'assessments_enabled': 'learning_assessment',
            'analytics_enabled': 'analytics_reporting',
            'financial_enabled': 'financial',
            'reporting_enabled': 'analytics_reporting',
            'communications_enabled': 'communication',
            'whatsapp_enabled': 'communication',
        }

        required_module = feature_to_module.get(feature_name)
        if required_module:
            return self.is_module_enabled(required_module)

        return False

    @property
    def deployed_modules(self) -> List[str]:
        """Get list of deployed modules."""
        return self.modules

    @property
    def test_markers(self) -> List[str]:
        """Get pytest markers to run for this scenario."""
        markers = ['critical']
        for module in self.deployed_modules:
            if module in self.MODULES:
                markers.extend(self.MODULES[module].get('test_markers', []))
        return list(set(markers))

    def validate_dependencies(self) -> bool:
        """Validate that all module dependencies are satisfied."""
        for module_name in self.modules:
            if module_name not in self.MODULES:
                raise ValueError(f"Unknown module: {module_name}")

            module_info = self.MODULES[module_name]
            required_deps = module_info['dependencies']

            for dep in required_deps:
                if dep not in self.modules:
                    raise ValueError(
                        f"Module '{module_name}' requires '{dep}' "
                        f"which is not in scenario '{self.scenario}'"
                    )

        return True

    def get_required_databases(self) -> List[str]:
        """Get list of database tables required for this scenario."""
        tables = []
        for module_name in self.modules:
            module_info = self.MODULES[module_name]
            tables.extend(module_info.get('database_tables', []))
        return list(set(tables))

    def get_minimum_test_coverage(self) -> Dict[str, int]:
        """Get minimum test coverage requirements per module."""
        coverage = {}
        for module_name in self.modules:
            module_info = self.MODULES[module_name]
            coverage[module_name] = module_info.get('test_coverage_min', 85)
        return coverage


# Global registry instance
_registry = None


def get_module_registry() -> ModuleRegistry:
    """Get or create the global module registry."""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry


def reset_registry():
    """Reset the global registry (mainly for testing)."""
    global _registry
    _registry = None
