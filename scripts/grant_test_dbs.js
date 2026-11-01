// One-time setup: let the scanner's Mongo user create and drop the three test databases.
// Edit SCANNER_USER and AUTH_DB, then run it as the Mongo admin (see steps in the chat).
const SCANNER_USER = "market_scanner_app";   // value of SCANNER_MONGO_USER
const AUTH_DB = "market_scanner";   // SCANNER_MONGO_AUTH_SOURCE, default is the project db

const dbs = ["test_market_scanner_probe", "test_market_scanner_mongo", "test_import_idempotent"];
const actions = ["find", "insert", "update", "remove", "createCollection", "createIndex",
  "dropCollection", "dropIndex", "listCollections", "listIndexes", "dropDatabase"];

const admin = db.getSiblingDB("admin");
const privileges = dbs.map(d => ({ resource: { db: d, collection: "" }, actions }));
if (admin.getRole("scannerTestDbs")) {
  admin.updateRole("scannerTestDbs", { privileges });
} else {
  admin.createRole({ role: "scannerTestDbs", roles: [], privileges });
}
db.getSiblingDB(AUTH_DB).grantRolesToUser(SCANNER_USER, [{ role: "scannerTestDbs", db: "admin" }]);
print("granted scannerTestDbs to " + SCANNER_USER);
