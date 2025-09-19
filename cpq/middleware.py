from django.utils.deprecation import MiddlewareMixin

class SaveLastDashboardSessionMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            path = request.path

            # Solo guardar si la URL empieza con /dashboard/
            if path.startswith("/dashboard/") or path == "/dashboard":
                request.session["last_dashboard_session"] = request.get_full_path()
        
        return None
