FROM node:20-alpine

# Install git for cloning openclaw-acp
RUN apk add --no-cache git

# Clone openclaw-acp (pinned to v0.4.0 for stability)
RUN git clone --depth 1 --branch v0.4.0 https://github.com/Virtual-Protocol/openclaw-acp.git /app

WORKDIR /app

# Install Node dependencies
RUN npm ci

# Create offering directory for TrustLayer agent
# Agent dir = sanitizeAgentName("TrustLayer") = "trustlayer"
# Offering  = "trustScore"
RUN mkdir -p src/seller/offerings/trustlayer/trustScore

# Copy our offering files from the Docker build context (acp-runtime/)
COPY offerings/trustScore/handlers.ts src/seller/offerings/trustlayer/trustScore/handlers.ts
COPY offerings/trustScore/offering.json src/seller/offerings/trustlayer/trustScore/offering.json

# Run the seller runtime as a foreground process (required by Railway)
CMD ["npx", "tsx", "src/seller/runtime/seller.ts"]
