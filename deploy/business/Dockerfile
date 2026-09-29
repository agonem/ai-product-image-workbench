# Java business service (prod-local). Build context: repository root.
FROM eclipse-temurin:21-jdk-noble AS build
WORKDIR /src
COPY contracts contracts
COPY business-service/.mvn business-service/.mvn
COPY business-service/mvnw business-service/pom.xml business-service/
COPY business-service/src business-service/src
# Tests run before release (python scripts/check.py); the image build only packages.
RUN cd business-service && chmod +x mvnw && ./mvnw -B -ntp -DskipTests package

FROM eclipse-temurin:21-jre-noble
WORKDIR /app
COPY --from=build /src/business-service/target/business-service.jar /app/business-service.jar
COPY deploy/business/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh
EXPOSE 8443
ENTRYPOINT ["/app/entrypoint.sh"]
