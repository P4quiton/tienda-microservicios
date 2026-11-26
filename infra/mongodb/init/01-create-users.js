
const password = process.env.MONGO_RESENAS_PASSWORD;

if (!password) {
    throw new Error("MONGO_RESENAS_PASSWORD is required");
}

const database = db.getSiblingDB("db_resenas");

database.createUser({
    user: "usr_resenas",
    pwd: password,
    roles: [
        {
            role: "readWrite",
            db: "db_resenas"
        }
    ]
});

database.createCollection("resenas");

print("MongoDB: db_resenas inicializada correctamente.");
