"""Feature validation module for ensuring data quality and consistency."""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
import great_expectations as ge
import pandas as pd
import numpy as np
from datetime import datetime
from statsmodels.tsa.stattools import adfuller
from pathlib import Path
from scipy import stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

class FeatureValidator:
    """Class for validating features based on predefined rules and thresholds."""
    
    def __init__(self, config_path: Union[str, Path]):
        """
        Initialize the FeatureValidator with configuration settings.
        
        Args:
            config_path: Path to the JSON configuration file
            
        Raises:
            FileNotFoundError: If the configuration file doesn't exist
            ValidationError: If the configuration file is invalid
        """
        self.config_path = Path(config_path)
        try:
            with open(self.config_path) as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValidationError(f"Error loading configuration: {str(e)}")
        
        # Initialize validation parameters
        self.null_threshold = self.config.get('null_threshold', 0.1)
        self.numeric_bounds = self.config.get('numeric_bounds', {})
        self.correlation_threshold = self.config.get('correlation_threshold', 0.95)
        self.stationarity_threshold = self.config.get('stationarity_threshold', 0.05)
        self.feature_groups = self.config.get('feature_groups', {})
        self.alert_thresholds = self.config.get('alert_thresholds', {})
        
        logger.info("FeatureValidator initialized successfully")

    def validate_nulls(self, df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """
        Validate null values in the dataset.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary with null validation results per feature
        """
        results = {}
        for column in df.columns:
            null_ratio = df[column].isnull().mean()
            results[column] = {
                'null_ratio': null_ratio,
                'exceeds_threshold': null_ratio > self.null_threshold
            }
        return results
        
    def validate_numeric_bounds(self, df: pd.DataFrame) -> Dict[str, Dict[str, bool]]:
        """
        Validate numeric bounds for specified features.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary with bounds validation results per feature
        """
        results = {}
        for feature, bounds in self.numeric_bounds.items():
            if feature in df.columns:
                values = df[feature].dropna()
                within_bounds = (values >= bounds['min']).all() and (values <= bounds['max']).all()
                results[feature] = {
                    'within_bounds': within_bounds,
                    'min_observed': values.min(),
                    'max_observed': values.max()
                }
        return results
        
    def validate_correlations(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Validate feature correlations.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary of highly correlated feature pairs
        """
        numeric_df = df.select_dtypes(include=[np.number])
        corr_matrix = numeric_df.corr()
        high_correlations = {}
        
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                correlation = abs(corr_matrix.iloc[i, j])
                if correlation > self.correlation_threshold:
                    pair = (corr_matrix.columns[i], corr_matrix.columns[j])
                    high_correlations[pair] = correlation
        
        return high_correlations
        
    def validate_stationarity(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Validate stationarity of time series features.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary with stationarity test results per feature
        """
        results = {}
        for feature in df.select_dtypes(include=[np.number]).columns:
            try:
                adf_result = adfuller(df[feature].dropna())
                is_stationary = adf_result[1] < self.stationarity_threshold
                results[feature] = {
                    'is_stationary': is_stationary,
                    'p_value': adf_result[1]
                }
            except Exception as e:
                results[feature] = {
                    'error': str(e)
                }
        return results
        
    def validate_feature_groups(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Validate feature group rules and relationships.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary with validation results per feature group
        """
        results = {}
        for group_name, group_config in self.feature_groups.items():
            group_results = {'valid': True, 'errors': []}
            
            # Check if all features exist
            missing_features = [f for f in group_config['features'] if f not in df.columns]
            if missing_features:
                group_results['valid'] = False
                group_results['errors'].append(f"Missing features: {missing_features}")
            
            # Apply rules if any
            if 'rules' in group_config:
                for target, rule in group_config['rules'].items():
                    try:
                        expected_values = df.eval(rule)
                        actual_values = df[target]
                        if not np.allclose(expected_values, actual_values, equal_nan=True):
                            group_results['valid'] = False
                            group_results['errors'].append(f"Rule validation failed for {target}")
                    except Exception as e:
                        group_results['valid'] = False
                        group_results['errors'].append(f"Rule evaluation error for {target}: {str(e)}")
            
            results[group_name] = group_results
        return results
        
    def create_expectation_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Create a complete validation expectation suite.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary containing all validation results
        """
        return {
            'null_validation': self.validate_nulls(df),
            'numeric_bounds_validation': self.validate_numeric_bounds(df),
            'correlation_validation': self.validate_correlations(df),
            'stationarity_validation': self.validate_stationarity(df),
            'feature_group_validation': self.validate_feature_groups(df)
        }

    def validate_features(self, df: pd.DataFrame) -> Dict:
        """
        Validate features in the DataFrame against defined expectations.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            
        Returns:
            Dict: Validation results for each feature
        """
        results = {}
        expectations = self.create_expectation_suite(df)
        
        for column, expect in expectations.items():
            column_results = {}
            
            # Check null values
            null_rate = (df[column].isnull().sum() / len(df)) * 100
            column_results['null_check'] = {
                'passed': null_rate <= expect['null_threshold'],
                'value': null_rate,
                'threshold': expect['null_threshold']
            }
            
            # Check numeric bounds if defined
            if column in self.numeric_bounds:
                bounds = self.numeric_bounds[column]
                values = df[column].dropna()
                
                min_check = values.min() >= bounds['min']
                max_check = values.max() <= bounds['max']
                
                column_results['bounds_check'] = {
                    'passed': min_check and max_check,
                    'min_value': values.min(),
                    'max_value': values.max(),
                    'bounds': bounds
                }
            
            results[column] = column_results
            
        return results

    def check_correlations(self, df: pd.DataFrame) -> List[Dict]:
        """
        Check for high correlations between features.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            
        Returns:
            List[Dict]: List of feature pairs with high correlations
        """
        numeric_df = df.select_dtypes(include=[np.number])
        corr_matrix = numeric_df.corr()
        
        high_correlations = []
        
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                correlation = abs(corr_matrix.iloc[i, j])
                
                if correlation >= self.correlation_threshold:
                    high_correlations.append({
                        'feature1': corr_matrix.columns[i],
                        'feature2': corr_matrix.columns[j],
                        'correlation': correlation
                    })
                    
        return high_correlations

    def check_stationarity(self, df: pd.DataFrame) -> Dict:
        """
        Check stationarity of features using Augmented Dickey-Fuller test.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            
        Returns:
            Dict: Stationarity test results for each feature
        """
        results = {}
        numeric_df = df.select_dtypes(include=[np.number])
        
        for column in numeric_df.columns:
            values = df[column].dropna()
            
            if len(values) < 20:  # Minimum required for meaningful test
                continue
                
            adf_result = adfuller(values)
            
            results[column] = {
                'statistic': adf_result[0],
                'p_value': adf_result[1],
                'is_stationary': adf_result[1] < self.stationarity_threshold
            }
            
        return results

    def validate_and_report(self, df: pd.DataFrame) -> Dict:
        """
        Perform all validations and generate a comprehensive report.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            
        Returns:
            Dict: Complete validation report
        """
        validation_results = self.validate_features(df)
        correlation_results = self.check_correlations(df)
        stationarity_results = self.check_stationarity(df)
        
        # Calculate overall metrics
        total_validations = sum(len(v) for v in validation_results.values())
        failed_validations = sum(
            1 for feature in validation_results.values()
            for check in feature.values()
            if not check['passed']
        )
        
        validation_success_rate = ((total_validations - failed_validations) / total_validations) * 100
        
        # Generate alerts
        alerts = []
        
        if validation_success_rate < self.alert_thresholds['failed_validations']:
            alerts.append({
                'level': 'ERROR',
                'message': f'Validation success rate ({validation_success_rate:.2f}%) below threshold '
                          f'({self.alert_thresholds["failed_validations"]}%)'
            })
            
        if len(correlation_results) > self.alert_thresholds['high_correlations']:
            alerts.append({
                'level': 'WARNING',
                'message': f'Found {len(correlation_results)} highly correlated feature pairs, '
                          f'threshold is {self.alert_thresholds["high_correlations"]}'
            })
            
        non_stationary_count = sum(1 for r in stationarity_results.values() if not r['is_stationary'])
        if non_stationary_count > self.alert_thresholds['non_stationary_features']:
            alerts.append({
                'level': 'WARNING',
                'message': f'Found {non_stationary_count} non-stationary features, '
                          f'threshold is {self.alert_thresholds["non_stationary_features"]}'
            })
            
        return {
            'validation_results': validation_results,
            'correlation_results': correlation_results,
            'stationarity_results': stationarity_results,
            'summary': {
                'validation_success_rate': validation_success_rate,
                'total_validations': total_validations,
                'failed_validations': failed_validations,
                'high_correlation_pairs': len(correlation_results),
                'non_stationary_features': non_stationary_count
            },
            'alerts': alerts
        }

    def get_feature_groups(self) -> Dict[str, List[str]]:
        """Return the configured feature groups."""
        return self.feature_groups

    def _load_config(self, config_path: str) -> dict:
        """Load the feature validation configuration from JSON file."""
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def create_expectation_suite(self, feature_names: List[str]):
        """Create Great Expectations suite for features"""
        try:
            suite = self.context.create_expectation_suite(
                expectation_suite_name="feature_validation_suite"
            )
            
            # Add expectations for each feature
            for feature in feature_names:
                # Basic expectations for all features
                suite.add_expectation(
                    ge.core.ExpectationConfiguration(
                        expectation_type="expect_column_to_exist",
                        kwargs={"column": feature}
                    )
                )
                
                suite.add_expectation(
                    ge.core.ExpectationConfiguration(
                        expectation_type="expect_column_values_to_not_be_null",
                        kwargs={
                            "column": feature,
                            "mostly": 1 - self.null_threshold
                        }
                    )
                )
                
                # Add numeric bounds if configured
                if feature in self.numeric_bounds:
                    bounds = self.numeric_bounds[feature]
                    
                    if bounds['min'] is not None:
                        suite.add_expectation(
                            ge.core.ExpectationConfiguration(
                                expectation_type="expect_column_values_to_be_between",
                                kwargs={
                                    "column": feature,
                                    "min_value": bounds['min'],
                                    "max_value": bounds['max']
                                }
                            )
                        )
            
            # Save suite
            self.context.save_expectation_suite(suite)
            return suite
            
        except Exception as e:
            self.logger.error(f"Error creating expectation suite: {e}")
            return None
    
    def validate_features(self, 
                         features_df: pd.DataFrame,
                         suite_name: str = "feature_validation_suite") -> Dict:
        """Validate features using Great Expectations"""
        try:
            # Convert DataFrame to Great Expectations dataset
            ge_df = ge.dataset.PandasDataset(features_df)
            
            # Run validation
            results = ge_df.validate(
                expectation_suite_name=suite_name,
                result_format="COMPLETE"
            )
            
            # Process results
            validation_results = {
                'timestamp': datetime.now().isoformat(),
                'success': results.success,
                'statistics': {
                    'evaluated_expectations': results.statistics['evaluated_expectations'],
                    'successful_expectations': results.statistics['successful_expectations'],
                    'unsuccessful_expectations': results.statistics['unsuccessful_expectations']
                },
                'results': []
            }
            
            # Add detailed results for each expectation
            for result in results.results:
                validation_results['results'].append({
                    'expectation_type': result.expectation_config.expectation_type,
                    'column': result.expectation_config.kwargs.get('column'),
                    'success': result.success,
                    'observed_value': result.result.get('observed_value'),
                    'details': result.result
                })
            
            # Save results
            os.makedirs(self.output_path, exist_ok=True)
            output_file = os.path.join(
                self.output_path,
                f"validation_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            with open(output_file, 'w') as f:
                json.dump(validation_results, f, indent=2)
            
            return validation_results
            
        except Exception as e:
            self.logger.error(f"Error validating features: {e}")
            return None
    
    def check_correlations(self, features_df: pd.DataFrame) -> Dict[str, List[str]]:
        """Check for highly correlated features"""
        try:
            # Calculate correlation matrix
            corr_matrix = features_df.corr()
            
            # Find highly correlated pairs
            high_corr = {}
            for i in range(len(corr_matrix.columns)):
                for j in range(i+1, len(corr_matrix.columns)):
                    if abs(corr_matrix.iloc[i,j]) > self.correlation_threshold:
                        feature1 = corr_matrix.columns[i]
                        feature2 = corr_matrix.columns[j]
                        
                        if feature1 not in high_corr:
                            high_corr[feature1] = []
                        high_corr[feature1].append(feature2)
            
            return high_corr
            
        except Exception as e:
            self.logger.error(f"Error checking correlations: {e}")
            return {}
    
    def check_stationarity(self, features_df: pd.DataFrame) -> Dict[str, bool]:
        """Check stationarity of features using ADF test"""
        try:
            # Run ADF test
            adf_result = adfuller(features_df.dropna())
            
            # Feature is considered stationary if p-value < threshold
            return {
                'is_stationary': adf_result[1] < self.stationarity_threshold,
                'p_value': adf_result[1],
                'test_statistic': adf_result[0]
            }
            
        except Exception as e:
            self.logger.error(f"Error checking stationarity: {e}")
            return {}
    
    def validate_and_report(self, features_df: pd.DataFrame) -> bool:
        """Run all validations and generate report"""
        try:
            # Create feature list
            feature_names = [col for col in features_df.columns 
                           if col not in ['timestamp', 'label', 'order_id']]
            
            # Create/update expectation suite
            suite = self.create_expectation_suite(feature_names)
            if not suite:
                return False
            
            # Run validation
            validation_results = self.validate_features(features_df)
            if not validation_results:
                return False
            
            # Check correlations
            correlations = self.check_correlations(features_df)
            
            # Check stationarity
            stationarity = self.check_stationarity(features_df)
            
            # Generate comprehensive report
            report = {
                'timestamp': datetime.now().isoformat(),
                'validation_results': validation_results,
                'correlations': correlations,
                'stationarity': stationarity,
                'summary': {
                    'total_features': len(feature_names),
                    'failed_validations': validation_results['failed_checks'],
                    'high_correlation_pairs': sum(len(v) for v in correlations.values()),
                    'non_stationary_features': sum(
                        1 for v in stationarity.values() 
                        if not v['is_stationary']
                    )
                }
            }
            
            # Save report
            report_file = os.path.join(
                self.output_path,
                f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            # Log summary
            self.logger.info(f"Validation Summary:")
            self.logger.info(f"Total Features: {report['summary']['total_features']}")
            self.logger.info(f"Failed Validations: {report['summary']['failed_validations']}")
            self.logger.info(f"High Correlation Pairs: {report['summary']['high_correlation_pairs']}")
            self.logger.info(f"Non-stationary Features: {report['summary']['non_stationary_features']}")
            
            return validation_results['success_percentage'] >= self.alert_thresholds['failed_validations']
            
        except Exception as e:
            self.logger.error(f"Error in validation and reporting: {e}")
            return False 