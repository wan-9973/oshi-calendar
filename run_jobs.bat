@echo off
rem === Daily jobs: cache retention (R2/R3) then crawler (R4) ===
rem Task Scheduler example (daily 03:00):
rem   schtasks /Create /SC DAILY /ST 03:00 /TN OshiCalendarJobs /TR "C:\oshi-calendar\run_jobs.bat"
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m src.retention >> logs\retention.log 2>&1
python -m src.crawler   >> logs\crawler.log 2>&1
