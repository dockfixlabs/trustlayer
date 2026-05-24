FROM node:20-alpine

WORKDIR /app

# Copy package definition
COPY package.json ./

# Install dependencies (includes acp-node-v2, tsx, etc.)
RUN npm install

# Copy seller source
COPY seller.ts ./

# Run the v2 seller
CMD ["npx", "tsx", "seller.ts"]
