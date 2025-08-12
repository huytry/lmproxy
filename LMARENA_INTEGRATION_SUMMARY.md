# LMArena Integration Onboarding Guide

## Overview

Welcome to the LMArena Integration region. This document helps you quickly get started with integrating and using LMArenaBridge endpoints directly, alongside legacy WebSocket bridge support.

This integration provides seamless communication between your PHP-based AI API gateway and LMArenaBridge services, enabling efficient data exchange and real-time updates.

## Quick-Start

- **Authenticate** using your API credentials to obtain a valid token.
- Use **direct integration endpoints** for RESTful communication with LMArenaBridge.
- Optionally, maintain **legacy WebSocket bridge** connections for backward compatibility.
- Follow the **data contract schemas** provided to format requests and parse responses correctly.
- Refer to usage examples below for common workflows.

## Key Concepts & Responsibilities

- **Direct Integration Endpoints**  
  RESTful HTTP endpoints that allow you to send and receive data directly to/from LMArenaBridge services. These endpoints handle operations such as session management, user state updates, and message passing.

- **Legacy WebSocket Bridge**  
  WebSocket-based communication channel retained for compatibility with older systems. It provides event-driven updates and bidirectional message flows.

- **Authentication Flow**  
  - Obtain an API token by submitting your credentials to the authentication endpoint.  
  - Include the token in the `Authorization` header for all subsequent requests.  
  - Tokens have expiration times; refresh as necessary.

- **Data Contracts**  
  - Requests and responses adhere to predefined JSON schemas.  
  - Ensure mandatory fields such as `sessionId`, `userId`, and `payload` are included where required.  
  - Handle error codes and messages according to documented conventions.

## Usage Examples

### Authenticate and Obtain Token

```
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "your-username",
  "password": "your-password"
}
```

Response:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR..."
}
```

### Send a Message via Direct Endpoint

```
POST /api/v1/messages/send
Authorization: Bearer {token}
Content-Type: application/json

{
  "sessionId": "abc123",
  "userId": "user_456",
  "payload": {
    "message": "Hello, LMArena!"
  }
}
```

Response:

```json
{
  "status": "success",
  "messageId": "msg789"
}
```

### Receive Updates (Legacy WebSocket Example)

Connect to the WebSocket endpoint at `wss://lmarena.example.com/ws` using your session token for authentication. Listen for events such as `messageReceived`, `sessionUpdate`, etc.

## Dependencies & Interactions

- **PHP AI API Gateway**  
  Hosts the integration logic and routes requests between your application and LMArenaBridge.

- **LMArenaBridge Services**  
  The backend services that process messages, manage sessions, and provide real-time data.

- **Authentication Server**  
  Handles token issuance and validation for secure access.

- **Legacy Systems** (optional)  
  May continue using WebSocket bridges until fully migrated to direct RESTful endpoints.

## Further Reading / Related Docs

- [LMArenaBridge API Reference](./LMArenaBridge/API_REFERENCE.md)  
- [Legacy WebSocket Bridge Guide](./LMArenaBridge/WEBSOCKET_BRIDGE.md)  
- [PHP AI API Gateway Integration Overview](./php/README.md)  
- [Authentication and Security Best Practices](./SECURITY.md)

---

By following this guide, you’ll be able to onboard quickly and integrate effectively with LMArenaBridge using both direct and legacy methods. Reach out to your integration support team for any questions.