// Edith networking: one shared satellite per match, through the relay (E.D.I.T.H-AI,
// edith_relay.py) over one WebSocket. docs/networkplan.md has the design and the messages.
#pragma once
#include <stdint.h>
#include <string>
#include <vector>

struct EdithMsg {
    bool binary;
    std::string data;                 // text JSON, or the binary message (b"EDR1" + len + name + ...)
};

struct EdithRoom {
    bool connected = false;
    std::string host;                 // empty until the relay has answered a hello
    std::vector<std::string> members;
    std::vector<std::string> ai;      // members whose voice companion runs (heard through it, not voice chat)
};

// Starts the connect/send/receive threads. `log` is the plugin's logger.
void EdithNet_Start(void (*log)(const char *fmt, ...));

// The relay URL (wss://.../edith/ws). Empty = disconnected.
void EdithNet_Configure(const std::string &url);

// Who we are, who else is in our match (display names), whether our voice companion runs.
// Sent to the relay on connect and whenever it changes.
void EdithNet_SetHello(const std::string &me, const std::vector<std::string> &others, bool ai, const char *build);

// Queue a message for the relay (dropped while disconnected; the oldest go when it backs up).
void EdithNet_SendText(const std::string &json);
void EdithNet_SendBinary(const void *data, size_t size);

// Messages received since the last call (room messages are handled here, not returned).
std::vector<EdithMsg> EdithNet_Take();

// The current room as the relay last described it.
EdithRoom EdithNet_Room();
