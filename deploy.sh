#!/bin/bash
set -e
echo "Syncing web/ to deployment..."
rsync -avz --delete web/ ./docs/
echo "Done. Push docs/ to trigger GitHub Pages deployment."
