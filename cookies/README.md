# Cookie files for RepeaterMock scraper
# These files contain authentication cookies for multiple RepeaterMock accounts.
# The scraper tries each account in order until one authenticates.
#
# After each run, the workflow commits updated cookies (with rotated refresh tokens)
# back to these files, so the next run has the latest valid token.
#
# WARNING: Do NOT use these cookies locally if GitHub Actions is also using them.
# RepeaterMock rotates the refresh token on every /auth/refresh call.
# Using it locally invalidates it for CI and vice versa.
