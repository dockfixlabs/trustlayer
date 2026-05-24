FROM node:20-alpine

WORKDIR /app

# Copy package definition
COPY package.json ./

# Install dependencies (includes acp-node-v2, tsx, etc.)
RUN npm install

# Copy all TypeScript source files
COPY seller.ts ./
COPY buyer.ts ./

# Default: run the v2 seller (buyer service overrides via Railway start command)
CMD ["npx", "tsx", "seller.ts"]
