-- Initialize database roles and permissions for RouteOpt
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'routeopt_app') THEN
      CREATE ROLE routeopt_app WITH LOGIN PASSWORD 'apppassword';
   END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE routeopt TO routeopt_app;
