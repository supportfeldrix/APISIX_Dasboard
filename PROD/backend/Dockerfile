# Use the existing backend image as base to avoid Docker Hub rate limits
# The python:3.11-slim base + pip dependencies are already cached in this image
FROM image-registry.openshift-image-registry.svc:5000/cro-apisix-prod/apisix-dashboard-backend:1.0.0

# Switch to root to update files
USER 0

WORKDIR /app

# Update application code only (dependencies already installed in base)
COPY app/ ./app/

# Ensure permissions are correct for OpenShift
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app

USER 1001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
