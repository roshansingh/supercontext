import express from "express";
import { Router } from "express";

const app = express();
const router = Router();

app.post("/123", handler);
router.get("/orders/:id", handler);
app.route("/batch").delete(handler);
const cjsApp = require("express")();
cjsApp.put("/inline-cjs", handler);
app.use("/mounted", router);

fetch("/api/orders", { method: "POST" });
void fetch(`/api/orders/${orderId}`);

function handler() {
  return undefined;
}
