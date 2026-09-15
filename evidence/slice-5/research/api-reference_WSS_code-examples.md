> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Code Example

## Complete TypeScript/JavaScript Example

A simple WebSocket client to help you get started. This example is intended for learning and experimentation not for production use.

```typescript theme={null}
import WebSocket from 'ws';

const WSS_URL = 'wss://api-qa.novig.us/tape';
const BEARER_TOKEN = ''

// Create WebSocket connection with Authorization header
const ws = new WebSocket(WSS_URL, {
  headers: {
    'Authorization': `Bearer ${BEARER_TOKEN}`
  }
});

// Connection opened
ws.on('open', () => {
  console.log('Connected to Novig WebSocket');
  
  // Subscribe to global tape (all markets)
  ws.send(JSON.stringify({ 
    event: 'subscribe',
    data: 'tape' 
  }));
  
  console.log('Subscription request sent');
});

// Listen for messages
ws.on('message', (data: WebSocket.Data) => {
  const message = data.toString();
  console.log('Received message:', message);
  
  try {
    const parsed = JSON.parse(message);
    console.log('Parsed data:', JSON.stringify(parsed, null, 2));
  } catch (error) {
    console.error('Failed to parse message:', error);
  }
});

// Handle errors
ws.on('error', (error: Error) => {
  console.error('WebSocket error:', error);
});

// Handle connection close
ws.on('close', (code: number, reason: string) => {
  console.log(`WebSocket closed. Code: ${code}, Reason: ${reason}`);
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('Closing WebSocket connection...');
  ws.close();
  process.exit(0);
});
```

Run with: `node quickstart.js`
