#!/usr/bin/env python3
"""
Tool to extract ML models from the machine-learning folder and prepare for use.
"""

import os
import sys
import shutil
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def find_models(source_dir: Path) -> list[Path]:
    """Find ML model files in the source directory.
    
    Args:
        source_dir: Directory to search for models
        
    Returns:
        List of model file paths
    """
    model_files = []
    
    # Look for .zip files which are likely saved models
    for path in source_dir.glob("**/*.zip"):
        if "ppo" in path.name.lower() or "model" in path.name.lower():
            model_files.append(path)
            
    return model_files

def copy_models(model_files: list[Path], target_dir: Path) -> None:
    """Copy model files to the target directory.
    
    Args:
        model_files: List of model file paths
        target_dir: Directory to copy models to
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    
    for model_file in model_files:
        target_path = target_dir / model_file.name
        logger.info(f"Copying {model_file.name} to {target_path}")
        shutil.copy2(model_file, target_path)
        
    # Create a default latest model symlink
    if model_files:
        latest_model = sorted(model_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        latest_path = target_dir / "latest_model.zip"
        
        # Remove existing symlink if it exists
        if latest_path.exists():
            latest_path.unlink()
            
        # Create symlink to latest model
        shutil.copy2(latest_model, latest_path)
        logger.info(f"Created latest model link to {latest_model.name}")

def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    try:
        # Get source and target directories
        source_dir = Path("ml/machine-learning")
        target_dir = Path("ml/models")
        
        if not source_dir.exists():
            logger.error(f"Source directory not found: {source_dir}")
            return 1
            
        # Find model files
        model_files = find_models(source_dir)
        
        if not model_files:
            logger.warning(f"No model files found in {source_dir}")
            return 0
            
        # Copy models
        copy_models(model_files, target_dir)
        
        logger.info(f"Successfully copied {len(model_files)} models to {target_dir}")
        return 0
        
    except Exception as e:
        logger.error(f"Error initializing models: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 