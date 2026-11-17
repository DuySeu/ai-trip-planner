import type { User } from "./api.types.ts";
import { apiRequest } from "./client.ts";

// POST /users - claim a name, or get the user who already has it
export async function claimUser(name: string): Promise<User> {
  return (await apiRequest<User>("/users", { method: "POST", body: JSON.stringify({ name }) })).data;
}
