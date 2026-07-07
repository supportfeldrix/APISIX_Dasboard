# Pre-built frontend — dist/ is built locally before oc start-build
# Build locally with: npx vite build
# Then deploy with: oc start-build apisix-dashboard-frontend --from-dir=. --follow
# Use internal registry image to avoid Docker Hub rate limits
FROM image-registry.openshift-image-registry.svc:5000/cro-apisix-uat/apisix-dashboard-frontend:1.0.0

# Switch to root to update files
USER 0

# Copy pre-built assets (built locally with vite build)
COPY dist/ /usr/share/nginx/html/

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Fix permissions for OpenShift
RUN chown -R 1001:0 /usr/share/nginx/html && \
    chmod -R g=u /usr/share/nginx/html && \
    chown -R 1001:0 /etc/nginx/conf.d && \
    chmod -R g=u /etc/nginx/conf.d

USER 1001

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
