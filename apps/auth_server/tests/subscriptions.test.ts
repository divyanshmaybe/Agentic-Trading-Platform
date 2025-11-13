import test from "node:test";
import assert from "node:assert/strict";
import { updateUserSubscriptions } from "../controllers/auth.controllers";
import { prisma } from "../lib/prisma";
import { ErrorHandling } from "../../../middleware/js/errorHandler";

type NextFn = (err?: any) => void;

const createResponse = () => {
  const res: any = {};
  res.status = (code: number) => {
    res.statusCode = code;
    return res;
  };
  res.json = (payload: any) => {
    res.body = payload;
    return payload;
  };
  return res;
};

test("updateUserSubscriptions subscribes new agent", async (t) => {
  const prismaAny = prisma as any;
  const originalFindUnique = prismaAny.user.findUnique;
  const originalUpdate = prismaAny.user.update;
  t.after(() => {
    prismaAny.user.findUnique = originalFindUnique;
    prismaAny.user.update = originalUpdate;
  });

  prismaAny.user.findUnique = async () => ({
    id: "user-1",
    subscriptions: ["low_risk"],
  });

  let updatedSubscriptions: string[] | undefined;
  prismaAny.user.update = async ({ data }: { data: { subscriptions: string[] } }) => {
    updatedSubscriptions = data.subscriptions;
    return { id: "user-1", subscriptions: data.subscriptions };
  };

  const req: any = {
    user: { _id: "user-1" },
    body: { action: "subscribe", agent: "alpha" },
  };
  const res = createResponse();
  const errors: any[] = [];
  const next: NextFn = (err) => {
    if (err) errors.push(err);
  };

  await updateUserSubscriptions(req, res, next as any);

  assert.equal(errors.length, 0);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(updatedSubscriptions, ["low_risk", "alpha"]);
  assert.deepEqual(res.body.data.subscriptions, ["low_risk", "alpha"]);
});

test("updateUserSubscriptions unsubscribes existing agent", async (t) => {
  const prismaAny = prisma as any;
  const originalFindUnique = prismaAny.user.findUnique;
  const originalUpdate = prismaAny.user.update;
  t.after(() => {
    prismaAny.user.findUnique = originalFindUnique;
    prismaAny.user.update = originalUpdate;
  });

  prismaAny.user.findUnique = async () => ({
    id: "user-8",
    subscriptions: ["high_risk", "alpha"],
  });

  let updatedSubscriptions: string[] | undefined;
  prismaAny.user.update = async ({ data }: { data: { subscriptions: string[] } }) => {
    updatedSubscriptions = data.subscriptions;
    return { id: "user-8", subscriptions: data.subscriptions };
  };

  const req: any = {
    user: { _id: "user-8" },
    body: { action: "unsubscribe", agent: "alpha" },
  };
  const res = createResponse();
  const errors: any[] = [];
  const next: NextFn = (err) => {
    if (err) errors.push(err);
  };

  await updateUserSubscriptions(req, res, next as any);

  assert.equal(errors.length, 0);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(updatedSubscriptions, ["high_risk"]);
  assert.deepEqual(res.body.data.subscriptions, ["high_risk"]);
});

test("updateUserSubscriptions rejects invalid agent", async (t) => {
  const prismaAny = prisma as any;
  const originalFindUnique = prismaAny.user.findUnique;
  const originalUpdate = prismaAny.user.update;
  t.after(() => {
    prismaAny.user.findUnique = originalFindUnique;
    prismaAny.user.update = originalUpdate;
  });

  let findUniqueCalled = false;
  prismaAny.user.findUnique = async () => {
    findUniqueCalled = true;
    return null;
  };
  prismaAny.user.update = async () => {
    throw new Error("Should not be called");
  };

  const req: any = {
    user: { _id: "user-5" },
    body: { action: "subscribe", agent: "invalid" },
  };
  const res = createResponse();
  const errors: any[] = [];
  const next: NextFn = (err) => {
    if (err) errors.push(err);
  };

  await updateUserSubscriptions(req, res, next as any);

  assert.equal(res.statusCode, undefined);
  assert.equal(findUniqueCalled, false);
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof ErrorHandling);
  assert.equal(errors[0].statusCode, 400);
  assert.match(errors[0].message, /agent must be one of/i);
});

