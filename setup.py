#!/usr/bin/env python3
"""
Automated Setup Script for Patient Monitoring System
This script will guide you through the complete setup process
"""

import subprocess
import sys
import os

def print_header(text):
    """Print formatted header"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60 + "\n")

def run_command(command, description):
    """Run a command and show progress"""
    print(f"→ {description}...")
    try:
        subprocess.run(command, check=True, shell=True)
        print(f"✓ {description} completed!\n")
        return True
    except subprocess.CalledProcessError:
        print(f"✗ {description} failed!\n")
        return False

def check_python_version():
    """Check if Python version is adequate"""
    print_header("Checking Python Version")
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major >= 3 and version.minor >= 8:
        print("✓ Python version is adequate\n")
        return True
    else:
        print("✗ Python 3.8 or higher is required\n")
        return False

def install_dependencies():
    """Install required Python packages"""
    print_header("Installing Dependencies")
    
    packages = [
        ("Flask", "Flask web framework"),
        ("Werkzeug", "Security utilities"),
        ("opencv-python", "Computer vision"),
        ("numpy", "Numerical computing")
    ]
    
    for package, description in packages:
        print(f"Installing {package} ({description})...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True
        )
        if result.returncode == 0:
            print(f"✓ {package} installed\n")
        else:
            print(f"✗ Failed to install {package}\n")
            return False
    
    return True

def initialize_database():
    """Initialize the database"""
    print_header("Initializing Database")
    
    try:
        from app import Database
        Database.init_db()
        print("✓ Database initialized successfully!\n")
        return True
    except Exception as e:
        print(f"✗ Database initialization failed: {e}\n")
        return False

def test_imports():
    """Test if all required modules can be imported"""
    print_header("Testing Imports")
    
    modules = [
        ("flask", "Flask"),
        ("werkzeug", "Werkzeug"),
        ("cv2", "OpenCV"),
        ("numpy", "NumPy"),
        ("sqlite3", "SQLite3 (built-in)")
    ]
    
    all_ok = True
    for module, name in modules:
        try:
            __import__(module)
            print(f"✓ {name} import successful")
        except ImportError:
            print(f"✗ {name} import failed")
            all_ok = False
    
    print()
    return all_ok

def create_config_file():
    """Create initial configuration"""
    print_header("Creating Configuration")
    
    print("Let's set up your camera configuration:")
    print("\nCamera options:")
    print("  0 - Default webcam")
    print("  1, 2, 3... - Other connected cameras")
    print("  http://IP:PORT/video - IP camera")
    
    camera_url = input("\nEnter camera source (press Enter for default '0'): ").strip()
    if not camera_url:
        camera_url = "0"
    
    print(f"\n✓ Camera will be set to: {camera_url}")
    print("  (You can change this later in the Settings page)\n")
    
    return True

def show_next_steps():
    """Display next steps for the user"""
    print_header("Setup Complete! 🎉")
    
    print("Your Patient Monitoring System is ready to use!")
    print("\nNext steps:")
    print("\n1. Start the application:")
    print("   python app.py")
    print("\n2. Open your browser:")
    print("   http://localhost:5000")
    print("\n3. Register your account")
    print("\n4. Configure camera in Settings")
    print("\n5. Start monitoring!")
    print("\n" + "="*60)
    print("\n📖 For detailed instructions, see:")
    print("   - QUICKSTART.md (Quick start guide)")
    print("   - README_WEBAPP.md (Complete documentation)")
    print("\n💡 Pro tip: Run 'python db_manager.py' anytime to:")
    print("   - View statistics")
    print("   - Backup database")
    print("   - Export data")
    print("\n" + "="*60 + "\n")

def main():
    """Main setup flow"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║                                                            ║")
    print("║     Patient Activity Monitoring System - Setup Wizard     ║")
    print("║                                                            ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    # Step 1: Check Python version
    if not check_python_version():
        print("Please upgrade Python to version 3.8 or higher")
        sys.exit(1)
    
    # Step 2: Test existing imports (maybe already installed)
    print_header("Checking Existing Packages")
    if test_imports():
        print("✓ All packages already installed!\n")
        skip_install = input("Skip package installation? (Y/n): ").strip().lower()
        if skip_install != 'n':
            print("Skipping package installation...\n")
        else:
            if not install_dependencies():
                print("Failed to install dependencies. Please install manually:")
                print("pip install Flask Werkzeug opencv-python numpy")
                sys.exit(1)
    else:
        # Step 3: Install dependencies
        if not install_dependencies():
            print("Failed to install dependencies. Please install manually:")
            print("pip install Flask Werkzeug opencv-python numpy")
            sys.exit(1)
    
    # Step 4: Initialize database
    if not initialize_database():
        print("Failed to initialize database.")
        print("You can try running: python db_manager.py")
        sys.exit(1)
    
    # Step 5: Create configuration
    create_config_file()
    
    # Step 6: Show next steps
    show_next_steps()
    
    # Ask if user wants to start now
    start_now = input("Would you like to start the application now? (y/N): ").strip().lower()
    if start_now == 'y':
        print("\nStarting application...")
        print("Press Ctrl+C to stop\n")
        try:
            subprocess.run([sys.executable, "app.py"])
        except KeyboardInterrupt:
            print("\n\nApplication stopped.")
    else:
        print("\nSetup complete! Run 'python app.py' when you're ready.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)
