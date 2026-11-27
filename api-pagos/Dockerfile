FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
COPY src src
RUN --mount=type=cache,target=/root/.m2 mvn -B -DskipTests package

FROM eclipse-temurin:21.0.10_7-jre-noble
WORKDIR /app
COPY --from=build /app/target/api-pagos-0.1.0.jar app.jar
USER 10001:10001
EXPOSE 8007
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
