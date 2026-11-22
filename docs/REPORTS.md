# Reports page (admins)

`GET /api/v1/analytics/summary?since&until&category&area` (reviewer/admin) feeds the **Reports** page.
Dates are whole days in pilot time (default: last 30 days, at most 366). Up to 31 days the volume chart
is per day, beyond that per week.

Each section states what it counts (also returned as `notes`):

| Section | Counts |
|---|---|
| Totals, status, category, areas, volume | Reports received in the range, deleted ones excluded. Status uses the same rule as the complaints list, so every count matches its list filter. |
| Time to resolve | Repair tasks first accepted in the range and now resolved; median and 90th percentile hours, and how many met the category's target. |
| Open backlog, top priorities | Unresolved repair tasks right now, ignoring the range. |
| Photo checks | Latest automatic check per report; flagged reports wait for a person. |

The page can show every chart as a table, export the numbers as CSV, and print or save as PDF.
Not included yet: a map heat layer.
