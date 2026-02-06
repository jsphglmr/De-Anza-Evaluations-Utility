"""
De Anza College — C-ID Course Equivalency Lookup (DearPyGui version)
High-performance GUI using GPU rendering for instant results display.
"""

import re
import os
from typing import Tuple

import dearpygui.dearpygui as dpg
import polars as pl

DEANZA_RED = (255, 50, 50)
DEANZA_GOLD = (197, 179, 88)
DEANZA_BLUE = (51, 122, 183)  # Blue for UI labels
DEANZA_LIGHT_BG = (245, 245, 245)
DEANZA_WHITE = (255, 255, 255)
DEANZA_GRAY = (128, 128, 128)

DATA_FILE = os.path.join(os.path.dirname(__file__), "cid.csv")
HOME_INSTITUTION = "De Anza College"

REQUIRED_COLS = ["C-ID #", "C-ID Descriptor", "Institution", "Local Course Title(s)", "Local Dept. Name & Number"]

# Search settings
SEARCH_DELAY_MS = 300
MIN_SEARCH_CHARS = 2
MAX_DISPLAY_RESULTS = 2000  # DearPyGui can handle more


class CidCsvError(Exception):
    """Raised when cid.csv is missing or not in the expected format."""
    pass


def load_data(path: str) -> pl.DataFrame:
    """
    Load C-ID CSV and preprocess for faster searches.
    Validates file existence, readability, and required columns.
    Raises CidCsvError with a clear message if validation fails.
    """
    path = os.path.abspath(path)
    
    if not os.path.isfile(path):
        raise CidCsvError(
            f"Data file not found: cid.csv\n\n"
            f"Place a file named 'cid.csv' in this folder:\n{os.path.dirname(path)}"
        )
    
    try:
        df = pl.read_csv(path, infer_schema_length=0)
    except Exception as e:
        raise CidCsvError(
            f"Could not read cid.csv as CSV.\n\n"
            f"Make sure the file is a valid CSV (comma-separated, UTF-8).\n"
            f"Detail: {e}"
        )
    
    if df.height == 0:
        raise CidCsvError(
            "cid.csv is empty.\n\n"
            "The file must contain a header row and at least one data row."
        )
    
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise CidCsvError(
            f"cid.csv is missing required column(s).\n\n"
            f"Missing: {', '.join(missing)}\n\n"
            f"Required columns (exact names):\n"
            + "\n".join(f"  • {c}" for c in REQUIRED_COLS)
        )
    
    # Add normalized columns for faster searching
    df = df.with_columns([
        pl.col("Institution").fill_null("").str.to_uppercase().alias("Institution_norm"),
        pl.col("Local Dept. Name & Number").fill_null("").str.to_uppercase().str.replace_all(r"\s+", " ").alias("Dept_norm"),
        pl.col("Local Course Title(s)").fill_null("").str.to_uppercase().alias("Title_norm"),
    ])
    
    return df


def extract_dept_and_number(course_str: str) -> Tuple[str, str]:
    """
    Extract department and course number from 'Local Dept. Name & Number'.
    E.g., 'ACCT 1A' -> ('ACCT', '1A')
    E.g., 'C D 1' -> ('C D', '1')
    """
    if not course_str:
        return "", ""
    
    # Match letters and spaces before the first digit/number
    match = re.match(r'^([A-Z\s]+?)\s+([0-9].*)$', course_str.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", course_str


def smart_search(df: pl.DataFrame, query: str) -> pl.DataFrame:
    """
    Smart search that handles any combination of keywords:
    - C-ID numbers (ACCT 110, BIOL 150)
    - Department codes (ACCT, BIOL, CS)
    - Institution names (Hartnell, De Anza, Foothill)
    - Course titles (Financial Accounting, Human Anatomy)
    """
    query = query.strip()
    if not query or len(query) < MIN_SEARCH_CHARS:
        return pl.DataFrame()
    
    # Check if query looks like a C-ID (dept code + number, e.g., "ACCT 110")
    cid_pattern = re.match(r'^([A-Z]{2,5})[\s-]+(\d+[A-Z]?)\s*(.*)$', query.upper())
    if cid_pattern:
        # Search C-ID column directly
        dept_code = cid_pattern.group(1)
        cid_number = cid_pattern.group(2)
        extra = cid_pattern.group(3).strip()
        
        # Try exact C-ID match first
        cid_query = f"{dept_code} {cid_number}"
        cid_results = df.filter(
            pl.col("C-ID #").fill_null("").str.to_uppercase().str.contains(cid_query)
        )
        
        if not cid_results.is_empty():
            # If there are extra keywords, filter by them too
            if extra:
                for keyword in extra.split():
                    cid_results = cid_results.filter(
                        pl.col("Institution_norm").str.contains(keyword) |
                        pl.col("Title_norm").str.contains(keyword)
                    )
            
            # Sort De Anza first
            is_de_anza = pl.col("Institution_norm").str.contains(HOME_INSTITUTION.upper())
            de_anza_rows = cid_results.filter(is_de_anza)
            other_rows = cid_results.filter(~is_de_anza)
            return pl.concat([de_anza_rows, other_rows]) if not other_rows.is_empty() else de_anza_rows
    
    keywords = query.upper().split()
    results = df
    
    # Identify institution keywords
    institution_keywords = []
    non_institution_keywords = []
    
    for keyword in keywords:
        institution_match = df.filter(pl.col("Institution_norm").str.contains(keyword))
        if not institution_match.is_empty():
            institution_keywords.append(keyword)
        else:
            non_institution_keywords.append(keyword)
    
    # Apply institution filters
    if institution_keywords:
        for inst_kw in institution_keywords:
            results = results.filter(pl.col("Institution_norm").str.contains(inst_kw))
    
    # Categorize remaining keywords
    common_words = {'DE', 'LA', 'OF', 'AND', 'THE', 'FOR', 'IN', 'ON', 'AT', 'TO', 'A', 'AN'}
    dept_pattern = re.compile(r'^[A-Z]{2,5}$')
    
    dept_keywords = []
    title_keywords = []
    
    for keyword in non_institution_keywords:
        if dept_pattern.match(keyword) and keyword not in common_words:
            dept_count = results.filter(pl.col("Dept_norm").str.contains(rf"\b{re.escape(keyword)}")).height
            title_count = results.filter(pl.col("Title_norm").str.contains(keyword)).height
            
            if dept_count > 0 and (title_count < dept_count * 10):
                dept_keywords.append(keyword)
            elif title_count > 0:
                title_keywords.append(keyword)
        else:
            title_keywords.append(keyword)
    
    # Apply filters
    for dept_kw in dept_keywords:
        results = results.filter(pl.col("Dept_norm").str.contains(rf"\b{re.escape(dept_kw)}"))
    
    for title_kw in title_keywords:
        results = results.filter(pl.col("Title_norm").str.contains(title_kw))
    
    if results.is_empty():
        return pl.DataFrame()
    
    # If no institution specified, get all institutions with matching C-IDs
    if not institution_keywords:
        cids = results["C-ID #"].unique().to_list()
        if not cids:
            return pl.DataFrame()
        
        all_results = df.filter(pl.col("C-ID #").is_in(cids))
        is_de_anza = pl.col("Institution_norm").str.contains(HOME_INSTITUTION.upper())
        de_anza_rows = all_results.filter(is_de_anza)
        other_rows = all_results.filter(~is_de_anza)
        results = pl.concat([de_anza_rows, other_rows]) if not other_rows.is_empty() else de_anza_rows
    
    return results.unique(
        subset=["C-ID #", "C-ID Descriptor", "Institution", "Local Dept. Name & Number", "Local Course Title(s)"]
    )


class EquivalencyApp:
    def __init__(self):
        self.df = None
        self.search_timer = None
        self.last_query = ""
        self.current_results = None
        
        # Selection state
        self.selected_dept = None
        self.selected_course = None
        self.de_anza_courses = None  # Will store De Anza courses with CIDs
        self._course_display_to_number = {}  # display str -> (first_num, full_number)
        self.load_error = None  # Set if cid.csv is missing or invalid
        
        # Load data
        try:
            self.df = load_data(DATA_FILE)
            print(f"Loaded {self.df.height} total rows from cid.csv")
        except CidCsvError as e:
            self.load_error = str(e)
            print(f"Data load error: {e}")
        except Exception as e:
            self.load_error = f"Unexpected error loading cid.csv:\n\n{e}"
            print(f"Error loading data: {e}")
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup DearPyGui interface."""
        dpg.create_context()
        
        # Increase font size globally (approximately 2pts larger)
        dpg.set_global_font_scale(1.15)
        
        # Custom theme for De Anza colors
        with dpg.theme() as main_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (240, 240, 245), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (255, 255, 255), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Button, DEANZA_RED, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 40, 80), category=dpg.mvThemeCat_Core)
                # Darker text in input fields
                dpg.add_theme_color(dpg.mvThemeCol_Text, (20, 20, 20), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (100, 100, 100), category=dpg.mvThemeCat_Core)
        
        # Table theme with better contrast
        with dpg.theme() as table_theme:
            with dpg.theme_component(dpg.mvTable):
                # Dark cells with white text for better contrast
                dpg.add_theme_color(dpg.mvThemeCol_Header, (30, 30, 35), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (40, 40, 50), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (50, 50, 60), category=dpg.mvThemeCat_Core)
            with dpg.theme_component(dpg.mvText):
                # White text for table cells
                dpg.add_theme_color(dpg.mvThemeCol_Text, (245, 245, 245), category=dpg.mvThemeCat_Core)
        
        # De Anza row theme - gold background with dark text
        with dpg.theme() as deanza_row_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, DEANZA_GOLD, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, DEANZA_GOLD, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, DEANZA_GOLD, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Text, (20, 20, 20), category=dpg.mvThemeCat_Core)
        
        self.deanza_theme = deanza_row_theme
        dpg.bind_theme(main_theme)
        
        # Main window
        with dpg.window(label="De Anza College — C-ID Course Equivalency Lookup", 
                       tag="main_window", width=1000, height=650):
            
            # Header
            dpg.add_text("C-ID Course Equivalency Lookup", color=DEANZA_RED)
            dpg.add_text("De Anza College", color=DEANZA_GOLD)
            dpg.add_spacer(height=10)
            
            # Selection area with two listboxes side by side
            with dpg.group(horizontal=True):
                # Left side: Department selection
                with dpg.group():
                    dpg.add_text("1. Select Department:", color=DEANZA_BLUE)
                    dpg.add_listbox(
                        tag="dept_listbox",
                        items=[],
                        callback=self.on_dept_selected,
                        width=150,
                        num_items=6,
                    )
                
                dpg.add_spacer(width=15)
                
                # Right side: Course selection
                with dpg.group():
                    dpg.add_text("2. Select Course:", color=DEANZA_BLUE)
                    dpg.add_listbox(
                        tag="course_listbox",
                        items=[],
                        callback=self.on_course_selected,
                        width=450,
                        num_items=6,
                    )
                
                dpg.add_spacer(width=15)
                
                # Info panel
                with dpg.group():
                    dpg.add_text("Selection:", color=DEANZA_BLUE)
                    dpg.add_text("Dept: None", tag="selected_dept_info", color=DEANZA_GRAY)
                    dpg.add_text("Course: None", tag="selected_course_info", color=DEANZA_GRAY)
                    dpg.add_spacer(height=5)
                    dpg.add_button(label="Clear Selection", callback=self.clear_selection, width=180)
            
            dpg.add_spacer(height=10)
            
            # Results count / error message
            dpg.add_text(
                self.load_error if self.load_error else "Ready - Select a department and course",
                tag="results_count",
                color=DEANZA_RED if not self.load_error else (180, 0, 0),
            )
            if self.load_error:
                dpg.add_text("Fix the issue above and restart the app.", tag="results_count_hint", color=DEANZA_GRAY)
            dpg.add_spacer(height=10)
            
            # Results table with sortable headers (click to sort!)
            with dpg.table(
                tag="results_table",
                header_row=True,
                resizable=True,
                policy=dpg.mvTable_SizingStretchProp,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True,
                scrollY=True,
                height=-1,
                sortable=True,
                callback=self.on_sort_callback,
            ):
                # Add sortable columns - store their IDs for mapping (C-ID first)
                self.col_0 = dpg.add_table_column(label="C-ID", width_fixed=True, init_width_or_weight=150)
                self.col_1 = dpg.add_table_column(label="School", width_fixed=True, init_width_or_weight=250)
                self.col_2 = dpg.add_table_column(label="Dept", width_fixed=True, init_width_or_weight=70)
                self.col_3 = dpg.add_table_column(label="Number", width_fixed=True, init_width_or_weight=100)
                self.col_4 = dpg.add_table_column(label="Title", width_stretch=True)
            
            # Apply table theme
            dpg.bind_item_theme("results_table", table_theme)
        
        # Setup viewport
        dpg.create_viewport(title="De Anza C-ID Lookup", width=1000, height=650)
        dpg.setup_dearpygui()
        dpg.show_viewport()
    
    def load_de_anza_courses(self):
        """Load and organize all De Anza courses that have CIDs."""
        if self.df is None:
            return
        
        # Filter for De Anza courses only
        de_anza_df = self.df.filter(
            pl.col("Institution").str.to_uppercase().str.contains("DE ANZA")
        )
        
        # Only keep courses with CIDs
        de_anza_df = de_anza_df.filter(
            pl.col("C-ID #").is_not_null() & (pl.col("C-ID #") != "")
        )
        
        # Extract department and course info
        # Match dept (letters/spaces) and number (starts with digit)
        de_anza_df = de_anza_df.with_columns([
            pl.col("Local Dept. Name & Number").str.extract(r'^([A-Z\s]+?)\s+([0-9].*)$', 1).fill_null("").str.strip_chars().alias("Dept"),
            pl.col("Local Dept. Name & Number").str.extract(r'^([A-Z\s]+?)\s+([0-9].*)$', 2).fill_null("").str.strip_chars().alias("Number"),
        ])
        
        # Remove rows without valid dept/number
        de_anza_df = de_anza_df.filter(
            (pl.col("Dept") != "") & (pl.col("Number") != "")
        )
        
        self.de_anza_courses = de_anza_df
        print(f"Loaded {de_anza_df.height} De Anza courses with CIDs")
        dpg.set_primary_window("main_window", True)
    
    def populate_departments(self):
        """Populate the department listbox with unique De Anza departments."""
        if self.de_anza_courses is None:
            return
        
        # Get unique departments, sorted
        departments = self.de_anza_courses["Dept"].unique().sort().to_list()
        
        if dpg.does_item_exist("dept_listbox"):
            dpg.configure_item("dept_listbox", items=departments)
            print(f"Populated {len(departments)} departments")
    
    def on_dept_selected(self, sender, app_data):
        """Called when a department is selected from the listbox."""
        self.selected_dept = app_data
        self.selected_course = None
        
        # Update info display
        if dpg.does_item_exist("selected_dept_info"):
            dpg.set_value("selected_dept_info", f"Department: {app_data}")
        if dpg.does_item_exist("selected_course_info"):
            dpg.set_value("selected_course_info", "Course: None")
        
        # Populate courses for this department
        self.populate_courses(app_data)
        
        # Show all courses in this department
        self.show_department_courses(app_data)
    
    def _first_course_number(self, number_str: str) -> str:
        """Get the first course number from '6A + BIOL 6C' -> '6A'."""
        if not number_str:
            return ""
        return number_str.split("+")[0].strip()
    
    def _natural_sort_key(self, s: str):
        """Sort key so 1, 1A, 1B, 2, 6A, 10, 40A order sensibly."""
        s = s.strip()
        i = 0
        digits = ""
        while i < len(s) and s[i].isdigit():
            digits += s[i]
            i += 1
        suffix = s[i:].strip()
        num = int(digits) if digits else 0
        return (num, suffix)
    
    def populate_courses(self, department):
        """Populate the course listbox with courses from the selected department."""
        if self.de_anza_courses is None:
            return
        
        # Filter courses by department
        dept_courses = self.de_anza_courses.filter(pl.col("Dept") == department)
        
        # One line per unique course number; keep first title and C-ID seen, truncated
        MAX_TITLE_LEN = 40
        seen = {}  # first_number -> (display_str, full_number for lookup)
        for row in dept_courses.iter_rows(named=True):
            number = row.get("Number", "")
            title = (row.get("Local Course Title(s)") or "").strip()
            cid = (row.get("C-ID #") or "").strip()
            first_num = self._first_course_number(number)
            if not first_num:
                continue
            if first_num not in seen:
                short = title[:MAX_TITLE_LEN] + ("..." if len(title) > MAX_TITLE_LEN else "")
                if cid:
                    display = f"{first_num} ({cid}) :: {short}" if short else f"{first_num} ({cid})"
                else:
                    display = f"{first_num} :: {short}" if short else first_num
                seen[first_num] = (display, number)
        
        # Sort by number (natural: 1, 1A, 1B, 2, 6A, 10, 40A)
        try:
            sorted_nums = sorted(seen.keys(), key=self._natural_sort_key)
        except (ValueError, TypeError):
            sorted_nums = sorted(seen.keys())
        
        course_items = [seen[n][0] for n in sorted_nums]
        course_items.insert(0, "")  # Blank entry to show all courses
        
        # Store display -> (first_num, full_number) for selection lookup
        self._course_display_to_number = {seen[n][0]: (n, seen[n][1]) for n in sorted_nums}
        self._course_display_to_number[""] = ("", "")
        
        if dpg.does_item_exist("course_listbox"):
            dpg.configure_item("course_listbox", items=course_items)
            print(f"Populated {len(course_items)-1} courses for {department} (plus 'all' option)")
    
    def on_course_selected(self, sender, app_data):
        """Called when a course is selected from the listbox."""
        if not self.selected_dept:
            return
        
        self.selected_course = app_data
        
        # If blank entry selected, show all department courses
        if not app_data or app_data.strip() == "":
            if dpg.does_item_exist("selected_course_info"):
                dpg.set_value("selected_course_info", "Course: (All courses)")
            self.show_department_courses(self.selected_dept)
            return
        
        # Update info display
        if dpg.does_item_exist("selected_course_info"):
            dpg.set_value("selected_course_info", f"Course: {app_data}")
        
        # Resolve display string to course number (e.g. "6A :: Title" -> "6A")
        course_number = app_data.split(" :: ")[0].strip() if " :: " in app_data else app_data.strip()
        if getattr(self, "_course_display_to_number", None):
            if app_data in self._course_display_to_number:
                course_number = self._course_display_to_number[app_data][0]
        
        # Find the CID for this course
        self.show_equivalencies(self.selected_dept, course_number)
    
    def show_department_courses(self, department):
        """Show all courses in the selected department from all schools."""
        if self.de_anza_courses is None:
            return
        
        # Get all De Anza courses in this department
        dept_courses = self.de_anza_courses.filter(pl.col("Dept") == department)
        
        if dept_courses.is_empty():
            dpg.set_value("results_count", "No courses found for this department")
            self.clear_table()
            return
        
        # Get all CIDs for this department
        cids = dept_courses["C-ID #"].unique().to_list()
        
        # Find all courses with these CIDs from all schools
        result_df = self.df.filter(pl.col("C-ID #").is_in(cids))
        
        if result_df.is_empty():
            dpg.set_value("results_count", "No courses found")
            self.clear_table()
            return
        
        # Store and display results
        self.current_results = result_df
        self.display_results(result_df, f"{department} Department")
    
    def show_equivalencies(self, department, course_number):
        """Show all schools offering courses equivalent to the selected De Anza course."""
        if self.df is None or self.de_anza_courses is None:
            return
        
        # Match by first course number (so "6A" matches "6A", "6A + BIOL 6C", etc.)
        number_match = (
            (pl.col("Number") == course_number)
            | pl.col("Number").str.starts_with(course_number + " ")
            | pl.col("Number").str.starts_with(course_number + "+")
        )
        de_anza_course = self.de_anza_courses.filter(
            (pl.col("Dept") == department) & number_match
        )
        
        if de_anza_course.is_empty():
            dpg.set_value("results_count", "Course not found")
            self.clear_table()
            return
        
        # Get the CID(s) for this course
        cids = de_anza_course["C-ID #"].unique().to_list()
        
        if not cids or cids[0] == "":
            dpg.set_value("results_count", "No CID found for this course")
            self.clear_table()
            return
        
        # Find all courses with these CIDs
        result_df = self.df.filter(pl.col("C-ID #").is_in(cids))
        
        if result_df.is_empty():
            dpg.set_value("results_count", "No equivalent courses found")
            self.clear_table()
            return
        
        # Store and display results
        self.current_results = result_df
        self.display_results(result_df, f"{department} {course_number}")
    
    def clear_selection(self):
        """Clear the current selection and reset the UI."""
        self.selected_dept = None
        self.selected_course = None
        
        # Clear listbox selections
        if dpg.does_item_exist("dept_listbox"):
            dpg.set_value("dept_listbox", "")
        if dpg.does_item_exist("course_listbox"):
            dpg.configure_item("course_listbox", items=[])
        
        # Clear info display
        if dpg.does_item_exist("selected_dept_info"):
            dpg.set_value("selected_dept_info", "Department: None")
        if dpg.does_item_exist("selected_course_info"):
            dpg.set_value("selected_course_info", "Course: None")
        
        # Clear table
        self.clear_table()
        if dpg.does_item_exist("results_count"):
            dpg.set_value("results_count", "Ready - Select a department and course")
    
    def on_sort_callback(self, sender, sort_specs):
        """Called when user clicks a column header to sort.
        Uses DearPyGui's native row reordering for efficient sorting.
        """
        try:
            # No sorting case
            if sort_specs is None:
                return
            
            # Get all table rows
            rows = dpg.get_item_children(sender, 1)
            if not rows:
                return
            
            # Get the sort specification (column_widget_id, direction)
            column_widget_id, direction = sort_specs[0]
            
            # Map column widget ID to column index (0-4)
            column_id_map = {
                self.col_0: 0,
                self.col_1: 1,
                self.col_2: 2,
                self.col_3: 3,
                self.col_4: 4,
            }
            
            column_index = column_id_map.get(column_widget_id)
            if column_index is None:
                print(f"Unknown column widget ID: {column_widget_id}")
                return
            
            print(f"Sorting column {column_index}, direction: {direction}")
            
            # Create a sortable list: [(row_id, cell_value), ...]
            sortable_list = []
            for row in rows:
                # Get all cells in this row (slot 1 = child widgets)
                cells = dpg.get_item_children(row, 1)
                if not cells or column_index >= len(cells):
                    continue
                
                cell = cells[column_index]
                # Get the value from the cell (could be text, button label, etc.)
                value = ""
                try:
                    value = dpg.get_value(cell)
                except:
                    # If get_value fails, try to get the label (for buttons)
                    try:
                        value = dpg.get_item_label(cell)
                    except:
                        pass
                
                sortable_list.append([row, value if value else ""])
            
            if not sortable_list:
                return
            
            # Sort the list based on cell values
            # direction is 1 for ascending, -1 for descending
            sortable_list.sort(key=lambda e: e[1], reverse=(direction < 0))
            
            # Create list of sorted row IDs
            new_order = [pair[0] for pair in sortable_list]
            
            # Reorder the table rows
            dpg.reorder_items(sender, 1, new_order)
            
            print(f"Sorted {len(new_order)} rows by column {column_index}")
            
        except Exception as e:
            print(f"Error in sort callback: {e}")
            import traceback
            traceback.print_exc()
    
    def on_search_change(self, sender, app_data):
        """Search callback - kept for future use but not currently active."""
        pass
    
    def do_search(self, query: str):
        """Execute search - kept for future use but not currently active."""
        pass
    
    def clear_table(self):
        """Clear all rows from results table."""
        if dpg.does_item_exist("results_table"):
            # Delete all child rows
            children = dpg.get_item_children("results_table", slot=1)  # slot 1 = rows
            if children:
                for child in children:
                    dpg.delete_item(child)
    
    def display_results(self, result_df: pl.DataFrame, query: str):
        """Display search results in table."""
        self.clear_table()
        
        total_rows = result_df.height
        unique_cids = result_df["C-ID #"].unique().to_list()
        
        # Limit results
        if total_rows > MAX_DISPLAY_RESULTS:
            result_df = result_df.head(MAX_DISPLAY_RESULTS)
            dpg.set_value("results_count", 
                         f'Found {len(unique_cids)} C-ID(s), {total_rows} course(s) - Showing first {MAX_DISPLAY_RESULTS}')
        else:
            dpg.set_value("results_count", 
                         f'Found {len(unique_cids)} C-ID(s), {total_rows} course(s)')
        
        # Add rows
        for row_dict in result_df.iter_rows(named=True):
            school = (row_dict.get("Institution") or "").strip()
            local_course = (row_dict.get("Local Dept. Name & Number") or "").strip()
            dept, number = extract_dept_and_number(local_course)
            title = (row_dict.get("Local Course Title(s)") or "").strip()
            cid = (row_dict.get("C-ID #") or "").strip()
            
            # Check if De Anza
            is_de_anza = HOME_INSTITUTION.upper() in school.upper()
            
            with dpg.table_row(parent="results_table"):
                # Column order: C-ID, School, Dept, Number, Title
                if is_de_anza:
                    btn1 = dpg.add_button(label=cid, width=-1, height=20, enabled=False)
                    btn2 = dpg.add_button(label=school, width=-1, height=20, enabled=False)
                    btn3 = dpg.add_button(label=dept, width=-1, height=20, enabled=False)
                    btn4 = dpg.add_button(label=number, width=-1, height=20, enabled=False)
                    btn5 = dpg.add_button(label=title, width=-1, height=20, enabled=False)
                    for btn in [btn1, btn2, btn3, btn4, btn5]:
                        dpg.bind_item_theme(btn, self.deanza_theme)
                else:
                    dpg.add_text(cid, color=(245, 245, 245))
                    dpg.add_text(school, color=(245, 245, 245))
                    dpg.add_text(dept, color=(245, 245, 245))
                    dpg.add_text(number, color=(245, 245, 245))
                    dpg.add_text(title, color=(245, 245, 245))
    
    def run(self):
        """Start the application."""
        # Load De Anza courses after UI is ready (skip if cid.csv failed to load)
        if not self.load_error:
            try:
                self.load_de_anza_courses()
                self.populate_departments()
            except Exception as e:
                print(f"Error loading De Anza courses: {e}")
                import traceback
                traceback.print_exc()
                if dpg.does_item_exist("results_count"):
                    dpg.set_value("results_count", f"Error after loading CSV: {e}")
        
        dpg.start_dearpygui()
        dpg.destroy_context()


def main():
    app = EquivalencyApp()
    app.run()


if __name__ == "__main__":
    main()
