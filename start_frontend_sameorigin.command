#!/bin/bash
# Same frontend, served on http://localhost:3001 with API calls sent through
# the dev server (package.json "proxy") instead of straight to :5001.
# For browsers that block cross-port requests to localhost.
cd "$(dirname "$0")/frontend"
PORT=3001 BROWSER=none REACT_APP_API_URL=http://localhost:3001 npm start
