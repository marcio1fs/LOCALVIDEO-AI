FROM node:20-alpine

WORKDIR /app

# Dependências do CRM (apenas o servidor Node, sem dependências externas)
COPY package.json ./
COPY server ./server
COPY frontend ./frontend

ENV CRM_PORT=4000
ENV CRM_HOST=0.0.0.0

EXPOSE 4000

CMD ["node", "server/server.js"]
