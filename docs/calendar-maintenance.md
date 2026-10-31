# Market calendar maintenance

`config/calendars.yaml` contains reviewed session closures and exceptional openings. The `us` calendar follows the [NYSE published trading calendar](https://www.nyse.com/trade/hours-calendars); `us_treasury` follows the [OPM federal holiday schedule](https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/) as a conservative proxy for Treasury daily-rate publication. The India calendar follows the [NSE cash-market holiday page](https://www.nseindia.com/resources/exchange-communication-holidays) and subsequent exchange circulars. A federal holiday is not automatically an equity-market closure: Good Friday and Columbus Day differ between the calendars.

The 2026 NSE calendar is reviewed. The 2027 NYSE and OPM dates are included. As of 31 October 2026, an official NSE 2027 cash-market calendar was not available. The 2027 India entry is deliberately `verified: false`. It yields `CALENDAR_UNVERIFIED` for daily data, and daily alert replay stops at an unverified session rather than treating a weekday as a known trading day. **This is an outstanding feed-readiness item**, not a guessed schedule.

Before 2027 India daily scoring is enabled, an operator must:

1. Obtain the annual NSE cash-market circular and check the exchange holiday page for later amendments and special sessions.
2. Enter every weekday closure and any exceptional open day, attach the official circular URL in this document, and set `verified: true` only after a second review.
3. Add tests for representative holidays, weekends, special sessions, the December/January boundary and a weekday that stays open. Run the full pytest suite.
4. Review the calendar monthly for ad hoc election, budget, weather or exchange notices. Amend it with a dated commit and replay affected historical scores and alerts.
5. Repeat the NYSE/OPM checks before each new year. Maintain separate publisher calendars for feeds whose actual release schedule differs from the market proxy.

Unknown years and unverified years fail closed. `sessions_between` returns no count across them, so freshness cannot be certified. The 60-session daily alert lookback is a bounded operational window; replay beyond it requires an event-sourced checkpoint or a longer verified calendar history.
