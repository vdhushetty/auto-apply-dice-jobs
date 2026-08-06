# dice_auto_apply/app_tkinter.py

import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import json
import pandas as pd
from datetime import datetime
import time
import logging
import subprocess

from core.authorization import DiceAuthorizationError, require_dice_automation_authorized
from core.dice_login import login_to_dice, update_dice_credentials, validate_dice_credentials
from core.main_script import (
    ApplicationStatus,
    RunMode,
    apply_to_job_url,
    build_diverse_candidate_pool,
    candidate_bucket_limits,
    fetch_jobs_with_requests,
    get_web_driver,
    rank_eligible_jobs,
)
from core.resumes import ResumeService, inspect_resume_catalog
from core.resumes.models import CloudProfile, ResumeError


AI_REVIEW_POLICY_LABELS = {
    "review_before_apply": "Review before apply",
    "skip_review": "Skip review",
}
AI_REVIEW_POLICY_VALUES = {label: value for value, label in AI_REVIEW_POLICY_LABELS.items()}


class DiceAutoBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dice Auto Apply Bot")
        self.root.geometry("900x700")

        # Set app icon if available
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "resources", "app_icon.png")
            if os.path.exists(icon_path):
                # For Windows
                if sys.platform == "win32":
                    self.root.iconbitmap(icon_path)
                # For macOS and others that support .png icons
                else:
                    img = tk.PhotoImage(file=icon_path)
                    self.root.iconphoto(True, img)
        except Exception as e:
            pass

        # Configure logging
        self.setup_logging()

        # Initialize variables
        self.driver = None
        self.job_thread = None
        self.login_test_thread = None
        self.running = False

        # Load configuration if exists
        self.load_config()

        # Create the tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Create tab frames
        self.main_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)
        self.logs_tab = ttk.Frame(self.notebook)

        # Add tabs to notebook
        self.notebook.add(self.main_tab, text="Run Bot")
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.add(self.logs_tab, text="Logs")

        # Set up UI for each tab
        self.setup_main_tab()
        self.setup_settings_tab()
        self.setup_logs_tab()

        # Log that app is started
        self.logger.info("Application started")

    def setup_logging(self):
        """Set up logging for the application"""
        # Create logs directory if needed
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)

        # Create log filename with timestamp
        log_file = os.path.join(logs_dir, f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self):
        """Load configuration from config file"""
        self.config_dir = os.path.join(os.path.dirname(__file__), "config")
        self.config_file = os.path.join(self.config_dir, "settings.json")
        self.local_config_file = os.path.join(self.config_dir, "settings.local.json")
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

        # Default values
        self.search_queries = [
            "AI ML",
            "Gen AI",
            "Agentic AI",
            "Data Engineer",
            "Data Analyst",
            "Machine Learning",
        ]
        self.exclude_keywords = [
            "Manager",
            "Director",
            ".net",
            "SAP",
            "java",
            "w2 only",
            "only w2",
            "no c2c",
            "only on w2",
            "w2 profiles only",
            "tester",
            "f2f",
        ]
        self.include_keywords = [
            "AI",
            "Artificial",
            "Inteligence",
            "Machine",
            "Learning",
            "ML",
            "Data",
            "NLP",
            "ETL",
            "Natural Language Processing",
            "analyst",
            "scientist",
            "senior",
            "cloud",
            "aws",
            "gcp",
            "Azure",
            "agentic",
            "python",
            "rag",
            "llm",
        ]
        self.headless_mode = False
        self.job_limit = 25
        self.run_mode = "preview"
        self.resume_mode = "static"
        self.resume_paths = {"aws": "", "azure": "", "gcp": ""}
        self.minimum_match_score = 35
        self.minimum_winner_margin = 5
        self.tailored_resume_output_dir = ".data/tailored_resumes"
        self.ai_resume_path = ""
        self.ai_resume_output_dir = ".data/ai_resumes"
        self.openai_model = "gpt-5.6-sol"
        self.ai_review_policy = "review_before_apply"

        # Try to load from file if it exists
        import json

        config = {}
        for path in (self.config_file, self.local_config_file):
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as config_file:
                    loaded = json.load(config_file)
                    if isinstance(loaded, dict):
                        config.update(loaded)
            except Exception as e:
                self.logger.error(f"Error loading configuration file {path}: {e}")
        self.search_queries = config.get("search_queries", self.search_queries)
        self.exclude_keywords = config.get("exclude_keywords", self.exclude_keywords)
        self.include_keywords = config.get("include_keywords", self.include_keywords)
        self.headless_mode = config.get("headless_mode", self.headless_mode)
        self.job_limit = config.get("job_application_limit", self.job_limit)
        self.run_mode = config.get("run_mode", self.run_mode)
        self.resume_mode = config.get("resume_mode", self.resume_mode)
        raw_paths = config.get("resume_paths", self.resume_paths)
        if isinstance(raw_paths, dict):
            self.resume_paths.update(
                {profile: str(raw_paths.get(profile, "")) for profile in self.resume_paths}
            )
        self.minimum_match_score = config.get("minimum_match_score", self.minimum_match_score)
        self.minimum_winner_margin = config.get("minimum_winner_margin", self.minimum_winner_margin)
        self.tailored_resume_output_dir = config.get(
            "tailored_resume_output_dir", self.tailored_resume_output_dir
        )
        self.ai_resume_path = str(config.get("ai_resume_path", self.ai_resume_path))
        self.ai_resume_output_dir = str(
            config.get("ai_resume_output_dir", self.ai_resume_output_dir)
        )
        self.openai_model = (
            os.getenv("OPENAI_MODEL", "").strip()
            or str(config.get("openai_model", self.openai_model)).strip()
            or "gpt-5.6-sol"
        )
        configured_review_policy = str(
            config.get("ai_review_policy", self.ai_review_policy)
        ).strip()
        if configured_review_policy in AI_REVIEW_POLICY_LABELS:
            self.ai_review_policy = configured_review_policy
        else:
            self.logger.warning(
                "Unknown AI review policy in settings; defaulting to review_before_apply"
            )
            self.ai_review_policy = "review_before_apply"
        self.logger.info("Configuration loaded successfully")

    def save_config(self):
        """Save configuration to config file"""
        # Ensure config directory exists
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

        try:
            api_key = self.openai_api_key_entry.get().strip()
            if self.persist_openai_key_var.get() and not api_key:
                raise ValueError("Enter an OpenAI API key before choosing to save it.")
            ai_review_policy = self.selected_ai_review_policy()
            if self.resume_mode_var.get() == "ai_bullets" and not ai_review_policy:
                raise ValueError(
                    "Choose Review before apply or Skip review before saving AI bullet settings."
                )
            config = {
                "search_queries": [
                    q.strip() for q in self.search_query_entry.get().split(",") if q.strip()
                ],
                "exclude_keywords": [
                    k.strip() for k in self.exclude_keywords_entry.get().split(",") if k.strip()
                ],
                "include_keywords": [
                    k.strip() for k in self.include_keywords_entry.get().split(",") if k.strip()
                ],
                "headless_mode": self.headless_var.get(),
                "job_application_limit": self.job_limit_var.get(),
                "run_mode": self.run_mode_var.get(),
                "resume_mode": self.resume_mode_var.get(),
                "resume_paths": {
                    profile: variable.get().strip()
                    for profile, variable in self.resume_path_vars.items()
                },
                "minimum_match_score": self.minimum_match_score_var.get(),
                "minimum_winner_margin": self.minimum_winner_margin_var.get(),
                "tailored_resume_output_dir": self.tailored_resume_output_dir,
                "ai_resume_path": self.ai_resume_path_var.get().strip(),
                "ai_resume_output_dir": self.ai_resume_output_dir,
                "openai_model": self.openai_model_var.get().strip() or "gpt-5.6-sol",
                "ai_review_policy": ai_review_policy or "review_before_apply",
            }

            temporary_config = f"{self.local_config_file}.tmp"
            with open(temporary_config, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            if os.name != "nt":
                os.chmod(temporary_config, 0o600)
            os.replace(temporary_config, self.local_config_file)

            # Update credentials in .env file
            username = self.username_entry.get()
            password = self.password_entry.get()

            if self.persist_credentials_var.get() and username and password:
                update_dice_credentials(username, password)

            if self.persist_openai_key_var.get():
                self.persist_openai_api_key(api_key)

            messagebox.showinfo("Settings Saved", "Your settings have been saved successfully.")
            self.logger.info("Settings saved successfully")

        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            messagebox.showerror("Error", f"Could not save settings: {str(e)}")

    @staticmethod
    def persist_openai_api_key(api_key):
        """Store the OpenAI key only in the ignored local environment file."""

        from dotenv import set_key

        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if not os.path.exists(env_path):
            with open(env_path, "a", encoding="utf-8"):
                pass
        set_key(env_path, "OPENAI_API_KEY", api_key)
        if os.name != "nt":
            os.chmod(env_path, 0o600)
        os.environ["OPENAI_API_KEY"] = api_key

    def calculate_time_estimate(self, jobs_count):
        """Calculate and display estimated completion time based on job count"""
        # Calculate based on historical data or defaults
        # Average time per job is around 10 seconds, but can vary
        avg_job_time = 10  # seconds
        total_seconds = jobs_count * avg_job_time

        # Add overhead time for initialization, etc.
        overhead_seconds = 60  # 1 minute overhead

        total_seconds += overhead_seconds

        # Calculate hours, minutes, seconds
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Create time string
        time_str = ""
        if hours > 0:
            time_str += f"{int(hours)} hours "
        if minutes > 0 or hours > 0:
            time_str += f"{int(minutes)} minutes "
        time_str += f"{int(seconds)} seconds"

        # Update UI with estimate
        self.update_status(f"Estimated completion time: {time_str}")
        return time_str

    def setup_main_tab(self):
        """Set up the main tab UI"""
        # Job queries section
        query_frame = ttk.LabelFrame(self.main_tab, text="Job Search Queries:")
        query_frame.pack(fill="x", padx=10, pady=10)

        # Search queries field
        self.search_query_entry = ttk.Entry(query_frame, width=70)
        self.search_query_entry.pack(fill="x", padx=10, pady=10)
        self.search_query_entry.insert(0, ", ".join(self.search_queries))

        # Keywords section
        keywords_frame = ttk.LabelFrame(
            self.main_tab, text="Optional Keywords for Better Job Filtering:"
        )
        keywords_frame.pack(fill="x", padx=10, pady=10)

        # Exclude keywords
        ttk.Label(keywords_frame, text="Exclude Keywords:").pack(anchor="w", padx=10, pady=5)
        self.exclude_keywords_entry = ttk.Entry(keywords_frame, width=70)
        self.exclude_keywords_entry.pack(fill="x", padx=10, pady=5)
        self.exclude_keywords_entry.insert(0, ", ".join(self.exclude_keywords))

        # Include keywords
        ttk.Label(keywords_frame, text="Include Keywords:").pack(anchor="w", padx=10, pady=5)
        self.include_keywords_entry = ttk.Entry(keywords_frame, width=70)
        self.include_keywords_entry.pack(fill="x", padx=10, pady=5)
        self.include_keywords_entry.insert(0, ", ".join(self.include_keywords))

        # Start button with custom style
        style = ttk.Style()
        style.configure("Green.TButton", background="gray", font=("Helvetica", 12))

        self.start_button = ttk.Button(
            self.main_tab, text="Start Preview", command=self.start_applying, style="Green.TButton"
        )
        self.start_button.pack(fill="x", padx=10, pady=10)

        # Stop button
        self.stop_button = ttk.Button(
            self.main_tab, text="Stop", command=self.stop_applying, state="disabled"
        )
        self.stop_button.pack(fill="x", padx=10, pady=5)

        # Progress section
        progress_frame = ttk.LabelFrame(self.main_tab, text="Progress")
        progress_frame.pack(fill="x", padx=10, pady=10)

        # Status label
        self.status_label = ttk.Label(progress_frame, text="Ready to start.")
        self.status_label.pack(padx=10, pady=5)

        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill="x", padx=10, pady=5)

        # Statistics frame
        stats_frame = ttk.Frame(progress_frame)
        stats_frame.pack(fill="x", padx=10, pady=5)

        # Add estimated time label
        estimated_time_frame = ttk.Frame(progress_frame)
        estimated_time_frame.pack(fill="x", padx=10, pady=2)
        ttk.Label(estimated_time_frame, text="Estimated Time:").grid(
            row=0, column=0, padx=5, pady=2
        )
        self.estimated_time_label = ttk.Label(estimated_time_frame, text="Calculating...")
        self.estimated_time_label.grid(row=0, column=1, padx=5, pady=2)

        # Total Jobs
        ttk.Label(stats_frame, text="Total Jobs:").grid(row=0, column=0, padx=5, pady=5)
        self.jobs_found_label = ttk.Label(stats_frame, text="0")
        self.jobs_found_label.grid(row=0, column=1, padx=5, pady=5)

        # Jobs applied
        ttk.Label(stats_frame, text="Jobs Applied:").grid(row=0, column=2, padx=5, pady=5)
        self.jobs_applied_label = ttk.Label(stats_frame, text="0")
        self.jobs_applied_label.grid(row=0, column=3, padx=5, pady=5)

        # Failed jobs
        ttk.Label(stats_frame, text="Failed Applications:").grid(row=0, column=4, padx=5, pady=5)
        self.jobs_failed_label = ttk.Label(stats_frame, text="0")
        self.jobs_failed_label.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(stats_frame, text="Jobs Skipped:").grid(row=0, column=6, padx=5, pady=5)
        self.jobs_skipped_label = ttk.Label(stats_frame, text="0")
        self.jobs_skipped_label.grid(row=0, column=7, padx=5, pady=5)

        ttk.Label(stats_frame, text="Ready / Verified:").grid(row=1, column=0, padx=5, pady=5)
        self.jobs_ready_label = ttk.Label(stats_frame, text="0")
        self.jobs_ready_label.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(stats_frame, text="Already Applied:").grid(row=1, column=2, padx=5, pady=5)
        self.jobs_already_applied_label = ttk.Label(stats_frame, text="0")
        self.jobs_already_applied_label.grid(row=1, column=3, padx=5, pady=5)

        # Excel Files section
        excel_frame = ttk.LabelFrame(self.main_tab, text="Excel Files")
        excel_frame.pack(fill="x", padx=10, pady=5)

        excel_buttons_frame = ttk.Frame(excel_frame)
        excel_buttons_frame.pack(fill="x", padx=5, pady=5)

        # Open Applied Jobs Excel
        applied_button = ttk.Button(
            excel_buttons_frame,
            text="Open Applied Jobs Excel",
            command=lambda: self.open_excel_file("applied_jobs.xlsx"),
        )
        applied_button.grid(row=0, column=0, padx=5, pady=5)

        # Open Not Applied Jobs Excel
        not_applied_button = ttk.Button(
            excel_buttons_frame,
            text="Open Not Applied Jobs Excel",
            command=lambda: self.open_excel_file("not_applied_jobs.xlsx"),
        )
        not_applied_button.grid(row=0, column=1, padx=5, pady=5)

        # Open Excluded Jobs Excel
        excluded_button = ttk.Button(
            excel_buttons_frame,
            text="Open Excluded Jobs Excel",
            command=lambda: self.open_excel_file("excluded_jobs.xlsx"),
        )
        excluded_button.grid(row=0, column=2, padx=5, pady=5)

        # Log section
        log_frame = ttk.LabelFrame(self.main_tab, text="Logs")
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Create text widget with scrollbar
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.config(state="disabled")  # Make it read-only

        # Add a handler that redirects logs to this widget
        self.log_handler = LogTextHandler(self.log_text)
        self.log_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        self.log_handler.setFormatter(formatter)
        self.logger.addHandler(self.log_handler)

    def open_excel_file(self, filename):
        """Open an Excel file using the system default application"""
        try:
            if not os.path.exists(filename):
                if filename == "excluded_jobs.xlsx":
                    # Create the file if it doesn't exist
                    df = pd.DataFrame(
                        columns=[
                            "Job Title",
                            "Job URL",
                            "Company",
                            "Location",
                            "Employment Type",
                            "Posted Date",
                            "Exclusion Reason",
                        ]
                    )
                    df.to_excel(filename, index=False)
                    self.logger.info(f"Created new {filename} file")
                else:
                    messagebox.showinfo(
                        "File Not Found", f"The file {filename} does not exist yet."
                    )
                    return

            # Open the file with the default system application
            if sys.platform == "win32":
                os.startfile(filename)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", filename])
            else:  # Linux
                subprocess.run(["xdg-open", filename])

            self.logger.info(f"Opened {filename}")
        except Exception as e:
            self.logger.error(f"Error opening {filename}: {e}")
            messagebox.showerror("Error", f"Could not open {filename}: {str(e)}")

    def setup_settings_tab(self):
        """Set up the settings tab UI"""
        # Login settings
        login_frame = ttk.LabelFrame(self.settings_tab, text="Dice Login")
        login_frame.pack(fill="x", padx=10, pady=10)

        # Username field
        username_frame = ttk.Frame(login_frame)
        username_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(username_frame, text="Username:", width=15).pack(side="left")
        self.username_entry = ttk.Entry(username_frame, width=50)
        self.username_entry.pack(side="left", fill="x", expand=True)

        # Password field
        password_frame = ttk.Frame(login_frame)
        password_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(password_frame, text="Password:", width=15).pack(side="left")
        self.password_entry = ttk.Entry(password_frame, show="*", width=50)
        self.password_entry.pack(side="left", fill="x", expand=True)

        self.persist_credentials_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            login_frame,
            text="Save Dice credentials in the local ignored .env file",
            variable=self.persist_credentials_var,
        ).pack(anchor="w", padx=10, pady=3)

        # Test login button
        self.test_login_button = ttk.Button(login_frame, text="Test Login", command=self.test_login)
        self.test_login_button.pack(pady=10)

        # Application settings
        settings_frame = ttk.LabelFrame(self.settings_tab, text="Application Settings")
        settings_frame.pack(fill="x", padx=10, pady=10)

        run_mode_frame = ttk.Frame(settings_frame)
        run_mode_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(run_mode_frame, text="Run mode:", width=24).pack(side="left")
        self.run_mode_var = tk.StringVar(value=self.run_mode)
        run_mode_combo = ttk.Combobox(
            run_mode_frame,
            textvariable=self.run_mode_var,
            values=("preview", "verify_upload", "submit"),
            state="readonly",
            width=18,
        )
        run_mode_combo.pack(side="left")
        run_mode_combo.bind("<<ComboboxSelected>>", self.on_run_mode_changed)
        self.run_mode_help_label = ttk.Label(
            settings_frame,
            text="Preview is the default and never clicks Apply.",
            wraplength=760,
        )
        self.run_mode_help_label.pack(anchor="w", padx=10, pady=(0, 5))

        # Headless mode checkbox
        self.headless_var = tk.BooleanVar(value=self.headless_mode)
        headless_check = ttk.Checkbutton(
            settings_frame,
            text="Run in headless mode (no visible browser)",
            variable=self.headless_var,
        )
        headless_check.pack(anchor="w", padx=10, pady=5)

        # Job limit
        limit_frame = ttk.Frame(settings_frame)
        limit_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(limit_frame, text="Maximum jobs to apply for:").pack(side="left")
        self.job_limit_var = tk.IntVar(value=self.job_limit)
        job_limit_spin = ttk.Spinbox(
            limit_frame, from_=1, to=100, width=5, textvariable=self.job_limit_var
        )
        job_limit_spin.pack(side="left", padx=5)

        resume_frame = ttk.LabelFrame(settings_frame, text="Resume Strategy")
        resume_frame.pack(fill="x", padx=10, pady=10)

        mode_row = ttk.Frame(resume_frame)
        mode_row.pack(fill="x", padx=5, pady=4)
        ttk.Label(mode_row, text="Mode:", width=16).pack(side="left")
        self.resume_mode_var = tk.StringVar(value=self.resume_mode)
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.resume_mode_var,
            values=("static", "tailored", "ai_bullets"),
            state="readonly",
            width=18,
        )
        mode_combo.pack(side="left")
        mode_combo.bind("<<ComboboxSelected>>", self.on_resume_mode_changed)

        self.resume_path_vars = {
            profile: tk.StringVar(value=self.resume_paths.get(profile, ""))
            for profile in ("aws", "azure", "gcp")
        }
        self.resume_paths_frame = ttk.Frame(resume_frame)
        self.resume_paths_frame.pack(fill="x")
        self.resume_path_rows = {}
        for profile, variable in self.resume_path_vars.items():
            row = ttk.Frame(self.resume_paths_frame)
            row.pack(fill="x", padx=5, pady=3)
            self.resume_path_rows[profile] = row
            ttk.Label(row, text=f"{profile.upper()} resume:", width=16).pack(side="left")
            ttk.Entry(row, textvariable=variable).pack(
                side="left", fill="x", expand=True, padx=(0, 5)
            )
            ttk.Button(
                row,
                text="Browse",
                command=lambda selected_profile=profile: self.browse_resume_file(selected_profile),
            ).pack(side="left")

        self.ai_resume_path_var = tk.StringVar(value=self.ai_resume_path)
        self.ai_resume_path_row = ttk.Frame(self.resume_paths_frame)
        ttk.Label(
            self.ai_resume_path_row,
            text="Base DOCX resume:",
            width=16,
        ).pack(side="left")
        ttk.Entry(
            self.ai_resume_path_row,
            textvariable=self.ai_resume_path_var,
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(
            self.ai_resume_path_row,
            text="Browse",
            command=self.browse_ai_resume_file,
        ).pack(side="left")

        self.ai_options_frame = ttk.Frame(resume_frame)
        api_key_row = ttk.Frame(self.ai_options_frame)
        api_key_row.pack(fill="x", padx=5, pady=3)
        ttk.Label(api_key_row, text="OpenAI API key:", width=16).pack(side="left")
        self.openai_api_key_entry = ttk.Entry(api_key_row, show="*", width=50)
        self.openai_api_key_entry.pack(side="left", fill="x", expand=True)

        model_row = ttk.Frame(self.ai_options_frame)
        model_row.pack(fill="x", padx=5, pady=3)
        ttk.Label(model_row, text="OpenAI model:", width=16).pack(side="left")
        self.openai_model_var = tk.StringVar(value=self.openai_model)
        ttk.Entry(model_row, textvariable=self.openai_model_var, width=30).pack(side="left")
        ttk.Label(model_row, text="(OPENAI_MODEL overrides this setting)").pack(side="left", padx=5)

        review_policy_row = ttk.Frame(self.ai_options_frame)
        review_policy_row.pack(fill="x", padx=5, pady=3)
        ttk.Label(review_policy_row, text="AI review policy:", width=16).pack(side="left")
        self.ai_review_policy_label_var = tk.StringVar(
            value=AI_REVIEW_POLICY_LABELS.get(self.ai_review_policy, "")
        )
        review_policy_combo = ttk.Combobox(
            review_policy_row,
            textvariable=self.ai_review_policy_label_var,
            values=tuple(AI_REVIEW_POLICY_LABELS.values()),
            state="readonly",
            width=22,
        )
        review_policy_combo.pack(side="left")
        review_policy_combo.bind("<<ComboboxSelected>>", self.on_ai_review_policy_changed)
        self.ai_review_policy_help_label = ttk.Label(
            self.ai_options_frame,
            wraplength=740,
        )
        self.ai_review_policy_help_label.pack(anchor="w", padx=5, pady=(0, 3))

        self.persist_openai_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.ai_options_frame,
            text="Save OpenAI key in the local ignored .env file",
            variable=self.persist_openai_key_var,
        ).pack(anchor="w", padx=5, pady=3)
        self.ai_options_frame.pack(fill="x", after=self.resume_paths_frame)

        self.threshold_row = ttk.Frame(resume_frame)
        self.threshold_row.pack(fill="x", padx=5, pady=4)
        ttk.Label(self.threshold_row, text="Minimum match:", width=16).pack(side="left")
        self.minimum_match_score_var = tk.DoubleVar(value=self.minimum_match_score)
        ttk.Spinbox(
            self.threshold_row,
            from_=0,
            to=100,
            increment=1,
            width=6,
            textvariable=self.minimum_match_score_var,
        ).pack(side="left")
        ttk.Label(self.threshold_row, text="% (lower matches are skipped)").pack(
            side="left", padx=5
        )

        self.margin_row = ttk.Frame(resume_frame)
        self.margin_row.pack(fill="x", padx=5, pady=4)
        ttk.Label(self.margin_row, text="Winner margin:", width=16).pack(side="left")
        self.minimum_winner_margin_var = tk.DoubleVar(value=self.minimum_winner_margin)
        ttk.Spinbox(
            self.margin_row,
            from_=0,
            to=25,
            increment=1,
            width=6,
            textvariable=self.minimum_winner_margin_var,
        ).pack(side="left")
        ttk.Label(self.margin_row, text="points (close matches are skipped)").pack(
            side="left", padx=5
        )

        self.validate_resumes_button = ttk.Button(
            resume_frame,
            text="Validate Three Resumes",
            command=self.validate_resume_catalog,
        )
        self.validate_resumes_button.pack(anchor="w", padx=5, pady=5)

        self.resume_mode_help_label = ttk.Label(
            resume_frame,
            text=(
                "Tailored mode accepts DOCX only and reorders exact, candidate-authored "
                "skills; it never invents qualifications."
            ),
            wraplength=760,
        )
        self.resume_mode_help_label.pack(anchor="w", padx=5, pady=(2, 5))

        # Save settings button
        self.save_settings_button = ttk.Button(
            settings_frame, text="Save Settings", command=self.save_config
        )
        self.save_settings_button.pack(pady=10)

        # User guide
        guide_frame = ttk.LabelFrame(self.settings_tab, text="User Guide")
        guide_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.guide_text = scrolledtext.ScrolledText(guide_frame, wrap=tk.WORD)
        self.guide_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Add user guide content
        guide_content = """
How to Use This Application
--------------------------

1. Enter your Dice.com login credentials in the Settings tab and test them
2. Enter job titles to search for (separated by commas)
3. Optionally specify include/exclude keywords to filter results
4. Configure either three cloud resumes or one base DOCX for AI bullet tailoring
5. For AI bullet mode, choose Review before apply or Skip review before starting
6. Run Preview first; it never clicks Apply
7. Use Verify Upload for one supervised filename check; Dice may retain a draft
8. Use Submit only after reviewing preview results

Understanding Keywords
--------------------

Include Keywords: Jobs must contain at least one of these words in the title
Exclude Keywords: Jobs containing any of these words will be skipped
Resume Match: Jobs below the configured title + description score are skipped

Finding Results
-------------

After the process completes, consolidated run reports are under .data/runs/.
Confirmed submissions are also appended to applied_jobs.xlsx.
        """
        self.guide_text.insert("1.0", guide_content)
        self.guide_text.config(state="disabled")  # Make it read-only

        # Get login details from environment (if available)
        from dotenv import load_dotenv

        load_dotenv()
        import os

        username = os.getenv("DICE_USERNAME", "")
        password = os.getenv("DICE_PASSWORD", "")
        openai_api_key = os.getenv("OPENAI_API_KEY", "")

        if username:
            self.username_entry.insert(0, username)
        if password:
            self.password_entry.insert(0, password)
        if openai_api_key:
            self.openai_api_key_entry.insert(0, openai_api_key)
        self.on_run_mode_changed()
        self.on_ai_review_policy_changed()
        self.on_resume_mode_changed()

    def on_run_mode_changed(self, _event=None):
        """Keep the primary action and side-effect warning aligned with run mode."""

        mode = RunMode(self.run_mode_var.get())
        labels = {
            RunMode.PREVIEW: (
                "Start Preview",
                "Preview reads job details and scores resumes but never clicks Apply.",
            ),
            RunMode.VERIFY_UPLOAD: (
                "Verify One Upload",
                "Upload verification is limited to one job and never clicks Next or Submit; "
                "Dice may retain a draft.",
            ),
            RunMode.SUBMIT: (
                "Start Submitting",
                "Submit mode may create external job applications after all safety checks pass.",
            ),
        }
        button_text, help_text = labels[mode]
        self.start_button.config(text=button_text)
        self.run_mode_help_label.config(text=help_text)

    def on_resume_mode_changed(self, _event=None):
        """Show only the source fields used by the selected resume strategy."""

        mode = self.resume_mode_var.get()
        ai_mode = mode == "ai_bullets"
        for row in self.resume_path_rows.values():
            row.pack_forget()
        self.ai_resume_path_row.pack_forget()
        self.ai_options_frame.pack_forget()

        if ai_mode:
            self.ai_resume_path_row.pack(fill="x", padx=5, pady=3)
            self.ai_options_frame.pack(fill="x", after=self.resume_paths_frame)
            self.margin_row.pack_forget()
            self.validate_resumes_button.config(text="Validate Base Resume")
            self.resume_mode_help_label.config(
                text=(
                    "AI bullet tailoring uses one DOCX, rewrites only supported experience "
                    "bullets, and preserves non-target structure and page count. Choose the "
                    "AI review policy before starting automation."
                )
            )
            if self.ai_resume_path_var.get().strip().lower().endswith(".pdf"):
                self.ai_resume_path_var.set("")
                messagebox.showwarning("DOCX Required", "AI bullet tailoring requires DOCX.")
            return

        for row in self.resume_path_rows.values():
            row.pack(fill="x", padx=5, pady=3)
        self.margin_row.pack(fill="x", padx=5, pady=4, after=self.threshold_row)
        self.validate_resumes_button.config(text="Validate Three Resumes")
        if mode == "tailored":
            self.resume_mode_help_label.config(
                text=(
                    "Tailored mode accepts DOCX only and reorders exact, candidate-authored "
                    "skills; it never invents qualifications."
                )
            )
            cleared = []
            for profile, variable in self.resume_path_vars.items():
                if variable.get().strip().lower().endswith(".pdf"):
                    variable.set("")
                    cleared.append(profile.upper())
            if cleared:
                messagebox.showwarning(
                    "DOCX Required",
                    "Tailored mode requires DOCX. Cleared PDF selections for: "
                    + ", ".join(cleared),
                )
        else:
            self.resume_mode_help_label.config(
                text=(
                    "Static mode scores the full job against three cloud resumes and uploads "
                    "the selected source file unchanged."
                )
            )

    def selected_ai_review_policy(self):
        """Return the stable value for the selected user-facing review-policy label."""

        return AI_REVIEW_POLICY_VALUES.get(self.ai_review_policy_label_var.get().strip(), "")

    def on_ai_review_policy_changed(self, _event=None):
        """Explain exactly what the selected AI review policy changes."""

        policy = self.selected_ai_review_policy()
        if policy == "review_before_apply":
            help_text = "Every generated DOCX opens for your approval before it can be uploaded."
        elif policy == "skip_review":
            help_text = (
                "Skips only human inspection of generated bullets. Evidence, structure, "
                "layout, matching, and upload-integrity checks still run."
            )
        else:
            help_text = "Choose a review policy before starting AI bullet automation."
        self.ai_review_policy_help_label.config(text=help_text)

    def browse_resume_file(self, profile):
        """Select one local resume without copying it into the repository."""

        if self.resume_mode_var.get() == "tailored":
            filetypes = (("Word document", "*.docx"),)
        else:
            filetypes = (
                ("Supported resumes", "*.docx *.pdf"),
                ("Word document", "*.docx"),
                ("PDF document", "*.pdf"),
            )
        selected = filedialog.askopenfilename(
            title=f"Select {profile.upper()} resume",
            filetypes=filetypes,
        )
        if selected:
            self.resume_path_vars[profile].set(selected)

    def browse_ai_resume_file(self):
        """Select the one DOCX source used by AI bullet tailoring."""

        selected = filedialog.askopenfilename(
            title="Select base DOCX resume",
            filetypes=(("Word document", "*.docx"),),
        )
        if selected:
            self.ai_resume_path_var.set(selected)

    def validate_resume_catalog(self):
        """Show privacy-safe compatibility diagnostics without Dice or OpenAI."""

        if self.resume_mode_var.get() == "ai_bullets":
            try:
                from docx import Document

                from core.resumes.bullet_documents import collect_editable_bullets
                from core.resumes.documents import validate_resume_path

                path = validate_resume_path(self.ai_resume_path_var.get().strip(), tailored=True)
                bullets = collect_editable_bullets(Document(str(path)))
                if not bullets:
                    raise ResumeError(
                        "No safely editable experience bullets were found in the base DOCX."
                    )
            except (ResumeError, ValueError, OSError) as exc:
                messagebox.showerror("Resume Validation", str(exc))
                return
            messagebox.showinfo(
                "Resume Validation",
                f"Base DOCX is AI-ready with {len(bullets)} editable experience bullets.",
            )
            return

        paths = {
            CloudProfile(profile): variable.get().strip()
            for profile, variable in self.resume_path_vars.items()
        }
        try:
            inspections = inspect_resume_catalog(paths)
        except (ResumeError, ValueError, OSError) as exc:
            messagebox.showerror("Resume Validation", str(exc))
            return
        lines = []
        for inspection in inspections:
            state = "tailored-ready" if inspection.tailored_compatible else "static-only"
            lines.append(
                f"{inspection.profile.value.upper()}: {inspection.format.upper()}, {state}, "
                f"{inspection.skill_slot_count} skill slots / "
                f"{inspection.skill_item_count} items, "
                f"{len(inspection.technology_terms)} recognized terms"
            )
            lines.extend(f"  - {warning}" for warning in inspection.warnings)
        messagebox.showinfo("Resume Validation", "\n".join(lines))

    def resume_settings_snapshot(self):
        """Capture Tk values on the UI thread before starting the worker."""

        return {
            "resume_mode": self.resume_mode_var.get(),
            "resume_paths": {
                profile: variable.get().strip()
                for profile, variable in self.resume_path_vars.items()
            },
            "minimum_match_score": self.minimum_match_score_var.get(),
            "minimum_winner_margin": self.minimum_winner_margin_var.get(),
            "tailored_resume_output_dir": self.tailored_resume_output_dir,
            "ai_resume_path": self.ai_resume_path_var.get().strip(),
            "ai_resume_output_dir": self.ai_resume_output_dir,
            "openai_model": (
                os.getenv("OPENAI_MODEL", "").strip()
                or self.openai_model_var.get().strip()
                or "gpt-5.6-sol"
            ),
            "ai_review_policy": self.selected_ai_review_policy(),
        }

    def review_ai_resume(self, job, generated_path, output_sha256):
        """Open one generated resume and obtain approval on the Tk UI thread."""

        completed = threading.Event()
        result = {"approved": False}

        def open_and_prompt():
            try:
                if sys.platform == "win32":
                    os.startfile(str(generated_path))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(generated_path)])
                else:
                    subprocess.Popen(["xdg-open", str(generated_path)])
                result["approved"] = messagebox.askyesno(
                    "Review AI-tailored Resume",
                    "The generated DOCX was opened for review.\n\n"
                    f"Job: {job.title}\n"
                    f"File: {generated_path.name}\n"
                    f"SHA-256: {output_sha256}\n\n"
                    "Approve this exact file for upload only after checking every bullet. "
                    "Choose No to skip the job.",
                )
            except Exception:
                messagebox.showerror(
                    "Resume Review",
                    "The generated resume could not be opened, so the job will be skipped.",
                )
            finally:
                completed.set()

        self.root.after(0, open_and_prompt)
        review_deadline = time.monotonic() + (15 * 60)
        while not completed.wait(timeout=0.25):
            if not self.running or time.monotonic() >= review_deadline:
                return False
        return bool(result["approved"])

    def setup_logs_tab(self):
        """Set up the logs tab UI"""
        # Create full log view
        log_frame = ttk.Frame(self.logs_tab)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Create text widget with scrollbar
        self.full_log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.full_log_text.pack(fill="both", expand=True)
        self.full_log_text.config(state="disabled")  # Make it read-only

        # Add button to load latest log file
        ttk.Button(self.logs_tab, text="Load Latest Log File", command=self.load_log_file).pack(
            pady=10
        )

    def load_log_file(self):
        """Load and display the latest log file"""
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        if not os.path.exists(logs_dir):
            messagebox.showinfo("No Logs", "No log files found.")
            return

        # Find all log files
        log_files = [
            os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.startswith("app_")
        ]

        if not log_files:
            messagebox.showinfo("No Logs", "No log files found.")
            return

        # Get the most recent log file
        latest_log = max(log_files, key=os.path.getmtime)

        try:
            # Read and display log content
            with open(latest_log, "r") as f:
                content = f.read()

            # Update the text widget
            self.full_log_text.config(state="normal")
            self.full_log_text.delete("1.0", tk.END)
            self.full_log_text.insert("1.0", content)
            self.full_log_text.config(state="disabled")

            self.logger.info(f"Loaded log file: {os.path.basename(latest_log)}")

        except Exception as e:
            self.logger.error(f"Error loading log file: {e}")
            messagebox.showerror("Error", f"Failed to load log file: {str(e)}")

    def test_login(self):
        """Test Dice login credentials"""
        if self.login_test_thread is not None and self.login_test_thread.is_alive():
            messagebox.showinfo(
                "Login Test",
                "The previous login check is still closing its browser. Please wait a moment.",
            )
            return

        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        headless = self.headless_var.get()

        if not username or not password:
            messagebox.showwarning(
                "Missing Credentials", "Please enter both username and password."
            )
            return

        # Disable button during testing
        self.test_login_button.config(state="disabled", text="Testing...")
        self.root.update_idletasks()
        result_queue = queue.Queue(maxsize=1)
        deadline = time.monotonic() + 100
        started_at = time.monotonic()
        last_elapsed = -1

        def poll_login_result():
            nonlocal last_elapsed
            try:
                success, error_message = result_queue.get_nowait()
            except queue.Empty:
                if time.monotonic() >= deadline:
                    self.test_login_complete(
                        False,
                        "Login test timed out. Its browser is still being closed; "
                        "wait a moment before retrying.",
                    )
                    return
                elapsed = int(time.monotonic() - started_at)
                if elapsed != last_elapsed:
                    self.test_login_button.config(text=f"Testing... {elapsed}s")
                    last_elapsed = elapsed
                self.root.after(100, poll_login_result)
                return
            self.test_login_complete(success, error_message)

        def test_login_thread():
            try:
                failure_messages = []
                success = validate_dice_credentials(
                    username,
                    password,
                    headless=headless,
                    failure_callback=failure_messages.append,
                )
                error_message = failure_messages[-1] if failure_messages else None
                result_queue.put((success, error_message))

            except Exception as e:
                result_queue.put((False, str(e)))

        # Run the test in a separate thread
        self.login_test_thread = threading.Thread(
            target=test_login_thread,
            daemon=True,
        )
        self.login_test_thread.start()
        self.root.after(100, poll_login_result)

    def test_login_complete(self, success, error_msg=None):
        """Handle login test completion"""
        # Re-enable the button
        self.test_login_button.config(state="normal", text="Test Login")

        if success:
            self.logger.info("Login test successful")
            messagebox.showinfo("Login Test", "Login successful!")
        else:
            error = (
                error_msg
                if error_msg
                else "Dice did not confirm the login. Check credentials or retry without headless mode."
            )
            self.logger.error(f"Login test failed: {error}")
            messagebox.showerror("Login Test", error)

    def start_applying(self):
        """Start the job application process"""
        # Validate inputs
        search_queries = [q.strip() for q in self.search_query_entry.get().split(",") if q.strip()]
        if not search_queries:
            messagebox.showwarning(
                "Missing Input", "Please enter at least one job title to search for."
            )
            return

        # Check for login credentials
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            messagebox.showwarning(
                "Missing Credentials", "Please enter Dice login credentials in the Settings tab."
            )
            self.notebook.select(1)  # Switch to settings tab
            return
        try:
            require_dice_automation_authorized()
        except DiceAuthorizationError as exc:
            messagebox.showerror(
                "Dice Authorization Required",
                str(exc),
            )
            return

        # Get keywords
        exclude_keywords = [
            k.strip() for k in self.exclude_keywords_entry.get().split(",") if k.strip()
        ]
        include_keywords = [
            k.strip() for k in self.include_keywords_entry.get().split(",") if k.strip()
        ]

        resume_settings = self.resume_settings_snapshot()
        run_mode = RunMode(self.run_mode_var.get())
        if (
            resume_settings["resume_mode"] == "ai_bullets"
            and not resume_settings["ai_review_policy"]
        ):
            messagebox.showerror(
                "AI Review Policy Required",
                "Choose Review before apply or Skip review before starting automation.",
            )
            self.notebook.select(1)
            return
        openai_api_key = self.openai_api_key_entry.get().strip()
        if (
            resume_settings["resume_mode"] == "ai_bullets"
            and run_mode is not RunMode.PREVIEW
            and not openai_api_key
        ):
            messagebox.showerror(
                "OpenAI API Key Required",
                "Enter an OpenAI API key before generating an AI-tailored resume.",
            )
            self.notebook.select(1)
            return
        try:
            resume_service = ResumeService.from_settings(
                resume_settings,
                api_key=openai_api_key or None,
                safety_identity=username,
                review_callback=self.review_ai_resume,
            )
        except (ResumeError, ValueError, OSError) as exc:
            messagebox.showerror("Resume Configuration", str(exc))
            self.notebook.select(1)
            return
        headless = bool(self.headless_var.get())
        try:
            job_limit = int(self.job_limit_var.get())
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror("Job Limit", "Job limit must be a whole number from 1 to 100.")
            return
        if not 1 <= job_limit <= 100:
            messagebox.showerror("Job Limit", "Job limit must be between 1 and 100.")
            return
        if run_mode is RunMode.VERIFY_UPLOAD:
            job_limit = 1
        if run_mode is not RunMode.PREVIEW and headless:
            headless = False
            messagebox.showinfo(
                "Visible Browser Required",
                "Upload verification and submission use a visible browser for supervision.",
            )

        confirmation = {
            RunMode.PREVIEW: (
                "Confirm Preview",
                "Score a bounded, diverse sample of discovered Dice jobs, then inspect "
                f"the highest-fit {job_limit}. Apply will never be clicked. Continue?",
            ),
            RunMode.VERIFY_UPLOAD: (
                "Confirm One Upload Check",
                "Open one eligible Easy Apply wizard and verify the selected resume filename. "
                "Next and Submit will not be clicked, but Dice may retain a draft. Continue?",
            ),
            RunMode.SUBMIT: (
                "Confirm External Submissions",
                "Score a bounded, diverse job sample by full descriptions, then submit "
                f"up to {job_limit} highest-fit applications using "
                f"{resume_settings['resume_mode']} resume mode. Continue?",
            ),
        }[run_mode]
        if resume_settings["resume_mode"] == "ai_bullets":
            review_policy = resume_settings["ai_review_policy"]
            review_label = AI_REVIEW_POLICY_LABELS[review_policy]
            if review_policy == "review_before_apply":
                review_warning = (
                    f"AI review policy: {review_label}. Every generated DOCX must be opened "
                    "and approved before upload."
                )
            else:
                review_warning = (
                    f"AI review policy: {review_label}. Skip review bypasses only human "
                    "inspection of the generated resume; evidence, document-integrity, "
                    "layout, matching, and upload checks remain enabled."
                )
            if run_mode is RunMode.PREVIEW:
                review_warning += " Preview does not generate or upload a resume."
            elif run_mode is RunMode.VERIFY_UPLOAD:
                review_warning += " Verify Upload may leave a Dice draft."
            confirmation = (confirmation[0], f"{confirmation[1]}\n\n{review_warning}")
        if not messagebox.askyesno(
            confirmation[0],
            confirmation[1],
        ):
            return

        # Update UI
        self.running = True
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.progress_bar["value"] = 0
        self.status_label.config(text="Starting...")

        # Reset counters
        self.jobs_found_label.config(text="0")
        self.jobs_applied_label.config(text="0")
        self.jobs_failed_label.config(text="0")
        self.jobs_skipped_label.config(text="0")
        self.jobs_ready_label.config(text="0")
        self.jobs_already_applied_label.config(text="0")

        # Clear log text
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

        # Run job application process in a separate thread
        self.job_thread = threading.Thread(
            target=self.run_job_application,
            args=(
                search_queries,
                include_keywords,
                exclude_keywords,
                username,
                password,
                resume_service,
                headless,
                job_limit,
                run_mode,
            ),
            daemon=True,
        )
        self.job_thread.start()

    def run_job_application(
        self,
        search_queries,
        include_keywords,
        exclude_keywords,
        username,
        password,
        resume_service,
        headless,
        job_limit,
        run_mode,
    ):
        """Run the job application process in a background thread"""
        driver = None
        try:
            # Record start time
            start_time = time.time()
            self.logger.info(f"Starting {run_mode.value} run with queries: {search_queries}")

            # Initialize web driver
            self.update_status("Initializing web driver...")
            driver = get_web_driver(headless=headless)

            # Login to Dice
            self.update_status("Logging in to Dice...")
            login_success = login_to_dice(driver, (username, password))
            if not login_success:
                self.update_status("Login failed. Please check your credentials.")
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "Login Failed", "Could not log in to Dice. Please check your credentials."
                    ),
                )
                driver.quit()
                self.reset_ui()
                return

            self.update_status("Login successful. Fetching jobs...")

            # Find jobs matching the search queries
            all_jobs = {}
            job_buckets = []
            excluded_jobs = []  # Track excluded jobs
            total_queries = len(search_queries)
            per_query_limits = candidate_bucket_limits(
                total_queries,
                application_limit=job_limit,
            )

            for i, query in enumerate(search_queries):
                if not self.running:
                    self.update_status("Stopped by user.")
                    driver.quit()
                    self.reset_ui()
                    return

                self.update_status(f"Searching for '{query}' ({i + 1}/{total_queries})...")

                # Use the fetch_jobs_with_requests function
                jobs, excluded = fetch_jobs_with_requests(
                    driver,
                    query,
                    include_keywords,
                    exclude_keywords,
                    max_pages=2,
                    max_included_jobs=per_query_limits[i],
                )

                # Track counts before adding new jobs
                jobs_before = len(all_jobs)
                query_bucket = []

                # Add unique jobs to dictionary
                for job in jobs:
                    if job["Job URL"] not in all_jobs:
                        job["Search Query"] = query
                        all_jobs[job["Job URL"]] = job
                        query_bucket.append(job)
                job_buckets.append(query_bucket)

                # Add excluded jobs
                excluded_jobs.extend(excluded)

                # Calculate current count
                current_count = len(all_jobs)

                # Update the counter after each query, capturing the current count
                count_to_display = current_count
                self.root.after(
                    0, lambda c=count_to_display: self.jobs_found_label.config(text=str(c))
                )

                # Print debug info
                print(
                    f"Query '{query}': Found {len(jobs)} total jobs, added {current_count - jobs_before} unique jobs"
                )

            # Make sure the final count is displayed
            final_count = len(all_jobs)
            self.update_status(f"Found {final_count} unique jobs matching criteria")
            self.root.after(0, lambda c=final_count: self.jobs_found_label.config(text=str(c)))

            # Check for already applied jobs
            self.update_status("Checking for already applied jobs...")
            applied_jobs_file = "applied_jobs.xlsx"
            already_applied = set()

            if os.path.exists(applied_jobs_file):
                try:
                    df_applied = pd.read_excel(applied_jobs_file)
                    already_applied = set(df_applied["Job URL"].dropna())
                    self.update_status(
                        f"Found {len(already_applied)} previously applied jobs to skip"
                    )
                except Exception as e:
                    raise RuntimeError(
                        "Could not safely read the prior-application ledger; run aborted."
                    ) from e

            # Filter out already applied jobs, build a bounded round-robin pool across
            # searches, and apply the cap only after full-description resume ranking.
            candidate_buckets = [
                [job for job in bucket if job["Job URL"] not in already_applied]
                for bucket in job_buckets
            ]
            candidate_jobs = build_diverse_candidate_pool(
                candidate_buckets,
                application_limit=job_limit,
            )
            self.update_status(
                f"Scoring a diverse pool of {len(candidate_jobs)} candidates by full "
                "job description..."
            )
            selection = rank_eligible_jobs(
                driver,
                candidate_jobs,
                resume_service,
                limit=job_limit,
                cancel_requested=lambda: not self.running,
                progress_callback=lambda current, total, title: self.update_status(
                    f"Scoring candidate {current}/{total}: {title}"
                ),
            )
            if selection.cancelled or not self.running:
                self.update_status("Stopped by user.")
                driver.quit()
                self.reset_ui()
                return

            jobs_to_apply = list(selection.selected_jobs)
            excluded_jobs.extend(selection.rejected_jobs)
            eligible_count = len(selection.selected_jobs) + len(selection.deferred_jobs)
            action_label = {
                RunMode.PREVIEW: "Previewing",
                RunMode.VERIFY_UPLOAD: "Verifying one upload for",
                RunMode.SUBMIT: "Applying to",
            }[run_mode]
            self.update_status(
                f"{action_label} the top {len(jobs_to_apply)} of "
                f"{eligible_count} resume-eligible jobs..."
            )

            # Save title-filtered and resume-ineligible jobs after the ranking pass so the
            # exclusion report explains every preflight rejection.
            excluded_file = "excluded_jobs.xlsx"
            if excluded_jobs:
                try:
                    df_excluded = pd.DataFrame(excluded_jobs)
                    df_excluded.to_excel(excluded_file, index=False)
                    self.logger.info(f"Saved {len(excluded_jobs)} excluded jobs to {excluded_file}")
                except Exception as e:
                    self.logger.error(f"Error saving excluded jobs: {e}")

            # Update the Total Jobs count to show the jobs that will be processed
            jobs_to_process_count = len(jobs_to_apply)
            self.root.after(
                0, lambda c=jobs_to_process_count: self.jobs_found_label.config(text=str(c))
            )

            # Calculate initial estimated time (assuming 10 jobs per minute)
            jobs_per_minute = 10.0
            total_jobs = len(jobs_to_apply)

            if total_jobs > 0:
                estimated_minutes = total_jobs / jobs_per_minute
                hours = int(estimated_minutes // 60)
                minutes = int(estimated_minutes % 60)

                # Format time string
                initial_estimate = ""
                if hours > 0:
                    initial_estimate += f"{hours} hours "
                if minutes > 0 or hours > 0:
                    initial_estimate += f"{minutes} minutes"
                else:
                    initial_estimate += "less than 1 minute"

                # Update both status and dedicated time label
                self.update_status(f"Estimated completion time: {initial_estimate}")
                self.root.after(
                    0, lambda t=initial_estimate: self.estimated_time_label.config(text=t)
                )

            # Start applying to jobs
            applied_count = 0
            failed_count = 0
            skipped_count = 0
            ready_count = 0
            already_applied_count = 0
            run_results = []

            # Variables for dynamic time estimation
            job_start_times = []
            job_processing_times = []

            for i, job in enumerate(jobs_to_apply):
                if not self.running:
                    self.update_status("Stopped by user.")
                    driver.quit()
                    self.reset_ui()
                    return

                # Record job start time for this specific job
                job_start_time = time.time()

                # Update progress
                progress = int((i / len(jobs_to_apply)) * 100) if jobs_to_apply else 0
                self.root.after(0, lambda p=progress: self.progress_bar.config(value=p))

                # Show job details in status
                job_title = job.get("Job Title", "Unknown")
                self.update_status(
                    f"{run_mode.value.replace('_', ' ').title()}: "
                    f"{job_title} ({i + 1}/{len(jobs_to_apply)})"
                )

                # Prepare and apply through the fail-closed resume-aware flow.
                try:
                    result = apply_to_job_url(
                        driver,
                        job,
                        resume_service,
                        run_mode=run_mode,
                        cancel_requested=lambda: not self.running,
                    )
                    run_results.append(dict(job))

                    # Record job completion time and calculate processing time for this job
                    job_end_time = time.time()
                    processing_time = job_end_time - job_start_time

                    # Keep track of job times for estimation
                    job_start_times.append(job_start_time)
                    job_processing_times.append(processing_time)

                    # Calculate dynamic time estimate after a few jobs
                    if i >= 2 and len(jobs_to_apply) > i + 1:
                        # Calculate average time per job based on the last few jobs
                        recent_times = job_processing_times[-min(10, len(job_processing_times)) :]
                        avg_time_per_job = sum(recent_times) / len(recent_times)

                        # Calculate remaining time
                        remaining_jobs = len(jobs_to_apply) - (i + 1)
                        remaining_seconds = avg_time_per_job * remaining_jobs

                        # Format remaining time string
                        remaining_hours = int(remaining_seconds // 3600)
                        remaining_minutes = int((remaining_seconds % 3600) // 60)
                        remaining_seconds = int(remaining_seconds % 60)

                        time_remaining = ""
                        if remaining_hours > 0:
                            time_remaining += f"{remaining_hours} hours "
                        if remaining_minutes > 0 or remaining_hours > 0:
                            time_remaining += f"{remaining_minutes} minutes "
                        time_remaining += f"{remaining_seconds} seconds"

                        # Update the estimated time label
                        self.root.after(
                            0, lambda t=time_remaining: self.estimated_time_label.config(text=t)
                        )

                    if result.status is ApplicationStatus.APPLIED:
                        applied_count += 1
                        # Update applied count
                        count_to_display = applied_count
                        self.root.after(
                            0,
                            lambda c=count_to_display: self.jobs_applied_label.config(text=str(c)),
                        )

                        # Save to applied jobs Excel file
                        try:
                            job["Applied"] = True
                            if os.path.exists(applied_jobs_file):
                                df_existing = pd.read_excel(applied_jobs_file)
                            else:
                                df_existing = pd.DataFrame(
                                    columns=[
                                        "Job Title",
                                        "Job URL",
                                        "Company",
                                        "Location",
                                        "Employment Type",
                                        "Posted Date",
                                        "Applied",
                                    ]
                                )

                            df_new = pd.DataFrame([job])
                            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                            df_combined.to_excel(applied_jobs_file, index=False)
                            if os.name != "nt":
                                os.chmod(applied_jobs_file, 0o600)
                        except Exception as e:
                            self.running = False
                            raise RuntimeError(
                                "Dice confirmed submission, but the local application ledger "
                                "could not be updated; stopping the run."
                            ) from e
                    elif result.status in {
                        ApplicationStatus.PREVIEW_READY,
                        ApplicationStatus.UPLOAD_VERIFIED,
                    }:
                        ready_count += 1
                        count_to_display = ready_count
                        self.root.after(
                            0,
                            lambda c=count_to_display: self.jobs_ready_label.config(text=str(c)),
                        )
                        job["Applied"] = False
                    elif result.status is ApplicationStatus.ALREADY_APPLIED:
                        already_applied_count += 1
                        count_to_display = already_applied_count
                        self.root.after(
                            0,
                            lambda c=count_to_display: self.jobs_already_applied_label.config(
                                text=str(c)
                            ),
                        )
                        job["Applied"] = True
                    elif result.status is ApplicationStatus.SKIPPED:
                        skipped_count += 1
                        count_to_display = skipped_count
                        self.root.after(
                            0,
                            lambda c=count_to_display: self.jobs_skipped_label.config(text=str(c)),
                        )
                        try:
                            job["Applied"] = False
                            job["Exclusion Reason"] = result.reason
                            if os.path.exists(excluded_file):
                                df_existing = pd.read_excel(excluded_file)
                            else:
                                df_existing = pd.DataFrame()
                            df_new = pd.DataFrame([job])
                            pd.concat([df_existing, df_new], ignore_index=True).to_excel(
                                excluded_file, index=False
                            )
                        except Exception as e:
                            self.logger.error(f"Error updating excluded jobs file: {e}")
                    else:
                        failed_count += 1
                        # Update failed count
                        count_to_display = failed_count
                        self.root.after(
                            0, lambda c=count_to_display: self.jobs_failed_label.config(text=str(c))
                        )

                        # Save to not applied jobs Excel file
                        not_applied_file = "not_applied_jobs.xlsx"
                        try:
                            if os.path.exists(not_applied_file):
                                df_existing = pd.read_excel(not_applied_file)
                            else:
                                df_existing = pd.DataFrame(
                                    columns=[
                                        "Job Title",
                                        "Job URL",
                                        "Company",
                                        "Location",
                                        "Employment Type",
                                        "Posted Date",
                                        "Applied",
                                    ]
                                )

                            job["Applied"] = False
                            job["Failure Reason"] = result.reason
                            df_new = pd.DataFrame([job])
                            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                            df_combined.to_excel(not_applied_file, index=False)
                        except Exception as e:
                            self.logger.error(f"Error updating not_applied Excel file: {e}")

                except Exception as e:
                    self.logger.error(f"Error applying to {job_title}: {e}")
                    failed_count += 1
                    job["Application Status"] = ApplicationStatus.FAILED.value
                    job["Application Reason"] = f"Unhandled {type(e).__name__}"
                    run_results.append(dict(job))
                    # Update failed count
                    count_to_display = failed_count
                    self.root.after(
                        0, lambda c=count_to_display: self.jobs_failed_label.config(text=str(c))
                    )

            # Compute execution time
            end_time = time.time()
            execution_time = end_time - start_time
            hours, remainder = divmod(execution_time, 3600)
            minutes, seconds = divmod(remainder, 60)

            time_str = f"{int(hours)}h {int(minutes)}m {seconds:.2f}s"
            self.update_status(
                f"Completed! Applied: {applied_count}, Ready/verified: {ready_count}, "
                f"Already applied: {already_applied_count}, Skipped: {skipped_count}, "
                f"Failed: {failed_count}, Time: {time_str}"
            )

            # Final progress update
            self.root.after(0, lambda: self.progress_bar.config(value=100))
            # Clear estimated time as we're done
            self.root.after(0, lambda: self.estimated_time_label.config(text="Completed"))

            # Save one consolidated, run-scoped report without job-description bodies.
            try:
                run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                run_directory = os.path.join(".data", "runs")
                os.makedirs(run_directory, mode=0o700, exist_ok=True)
                report_path = os.path.join(run_directory, f"{run_id}-{run_mode.value}-results.xlsx")
                if run_results:
                    pd.DataFrame(run_results).to_excel(report_path, index=False)
                    if os.name != "nt":
                        os.chmod(report_path, 0o600)
                job_data = {
                    "Run ID": run_id,
                    "Run Mode": run_mode.value,
                    "Total Jobs Found": len(all_jobs),
                    "Jobs Applied": applied_count,
                    "Jobs Ready or Upload Verified": ready_count,
                    "Jobs Already Applied": already_applied_count,
                    "Jobs Skipped": skipped_count,
                    "Jobs Failed": failed_count,
                    "Execution Time": time_str,
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                summary_path = os.path.join(
                    run_directory, f"{run_id}-{run_mode.value}-summary.json"
                )
                with open(summary_path, "w", encoding="utf-8") as f:
                    json.dump(job_data, f, indent=4)
                if os.name != "nt":
                    os.chmod(summary_path, 0o600)
                self.logger.info(f"Run report saved under {run_directory}")
            except Exception as e:
                self.logger.error(f"Error saving job data: {e}")

            # Show completion message
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Process Complete",
                    f"Application process completed!\n\n"
                    f"Applied to {applied_count} jobs\n"
                    f"Ready or upload verified: {ready_count}\n"
                    f"Already applied: {already_applied_count}\n"
                    f"Skipped {skipped_count} jobs\n"
                    f"Failed for {failed_count} jobs\n\n"
                    f"Total execution time: {time_str}",
                ),
            )

            # Clean up
            driver.quit()

        except Exception as e:
            self.logger.error(f"Error in job application process: {e}")
            self.update_status(f"Error: {str(e)}")
            error_message = str(e)
            self.root.after(
                0,
                lambda message=error_message: messagebox.showerror(
                    "Error", f"An error occurred: {message}"
                ),
            )
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            # Reset UI
            self.reset_ui()

    def stop_applying(self):
        """Stop the job application process"""
        if not self.running:
            return

        self.running = False
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Stopping... Please wait.")
        self.logger.info("User requested to stop the application process")

    def reset_ui(self):
        """Reset UI after job completion or stop"""
        self.running = False
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled", text="Stop")

    def update_status(self, message):
        """Update status message and log it"""
        self.logger.info(message)
        self.root.after(0, lambda msg=message: self.status_label.config(text=msg))


class LogTextHandler(logging.Handler):
    """Custom log handler that redirects logs to a tk Text widget"""

    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)

        def append_log():
            self.text_widget.config(state="normal")
            self.text_widget.insert("end", msg + "\n")
            self.text_widget.see("end")  # Scroll to the bottom
            self.text_widget.config(state="disabled")

        # Schedule the update in the main thread
        self.text_widget.after(0, append_log)


def main():
    root = tk.Tk()
    app = DiceAutoBotApp(root)
    root.protocol("WM_DELETE_WINDOW", root.quit)
    root.mainloop()


if __name__ == "__main__":
    main()
