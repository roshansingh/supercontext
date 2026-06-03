using Microsoft.AspNetCore.Builder;

public class Startup
{
    public void Configure(WebApplication app)
    {
        var path = GetPath();
        app.MapGet(path, () => "ok");
    }
}
