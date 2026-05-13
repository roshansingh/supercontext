import express from "express";
import { Router } from "express";
import fastify from "fastify";
import KoaRouter from "@koa/router";
import axios from "axios";

const app = express();
const router = Router();
const fastifyApp = fastify();
const koaRouter = new KoaRouter();
const USERS_PATH = "/api/users";
const api = axios.create({ baseURL: "http://localhost:3000" });

app.post("/123", handler);
router.get("/orders/:id", handler);
app.route("/batch").delete(handler);
const cjsApp = require("express")();
cjsApp.put("/inline-cjs", handler);
app.use("/mounted", router);
fastifyApp.get("/health", handler);
fastifyApp.route({ method: "POST", url: "/fastify-orders", handler });
koaRouter.put("/koa-users/:id", handler);

fetch("/api/orders", { method: "POST" });
void fetch(`/api/orders/${orderId}`);
fetch(USERS_PATH);
api.get("/api/profile");
fetch(`${process.env.API_HOST}/api/config`);

function handler() {
  return undefined;
}
