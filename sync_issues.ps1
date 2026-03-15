# sync_issues.ps1
# This script uses the GitHub CLI (gh) to synchronize issue statuses.
# Ensure you are logged in using 'gh auth login' before running.

Write-Host "--- Resolving Fixed Issues ---" -ForegroundColor Green
gh issue close 19 --comment "Resolved: Security Audit mitigations (chroot, timeouts, token redaction) active."
gh issue close 13 --comment "Resolved: Automated scenario validation and quality scoring implemented via linter.py."
gh issue close 12 --comment "Resolved: Integrated Visual Suite provides comprehensive analytics and dashboard."
gh issue close 11 --comment "Resolved: Standardized error handling and plugin timeouts implemented."
gh issue close 5 --comment "Resolved: AES Schema validation and linter prevent scenario runtime errors."
gh issue close 3 --comment "Resolved: Result export to CSV, JSON, and HTML formats fully supported."
gh issue close 15 --comment "Resolved: Native LangChain/LangGraph integration adapter added to ecosystem."
gh issue close 22 --comment "Resolved: Architectural documentation comprehensively updated."

Write-Host ""
Write-Host "--- Creating New Feature Issues ---" -ForegroundColor Red
gh issue create --title "[FEATURE] Mobile-Responsive Visual Console" --body "Implement CSS Breakpoints, drawer sidebars, and mobile-optimized viewports for the Visual Suite dashboard."
gh issue create --title "[FEATURE] Visual Suite Migration: Mermaid to React Flow" --body "Replace static SVG diagrams with interactive React Flow nodes for zooming and panning agent trajectories."
gh issue create --title "[FEATURE] Scenario Editor: Drag-and-Drop Node Reordering" --body "Allow users to visually rearrange scenario tasks/steps using a drag-n-drop interface in the web console."
gh issue create --title "[SCENARIO] End-to-End Validation: Ecommerce Customer Refund" --body "Create and validate a complex multi-turn refund scenario in the ecommerce industry to test end-to-end tool orchestration."

Write-Host ""
Write-Host "Sync complete." -ForegroundColor Cyan
