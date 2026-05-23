const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(
  path.join(__dirname, "..", "static", "house.html"),
  "utf8",
);

assert(html.includes("conversationSidebar"), "missing conversation sidebar");
assert(html.includes("newConversationBtn"), "missing new conversation button");
assert(html.includes("HOUSE_AGENT_CONVERSATIONS"), "missing localStorage key");
assert(html.includes("demoUserId"), "missing per-conversation demo user id");
assert(html.includes("createNewConversation"), "missing new conversation handler");
assert(html.includes("deleteConversation"), "missing delete conversation handler");
assert(!html.includes('user_id: "159"'), "fixed user_id should not be used");

console.log("frontend conversation UI checks passed");
