using Microsoft.AspNetCore.Mvc;

namespace Demo.Api
{
    [Route("articles")]
    public class ArticlesController
    {
        [HttpGet("{slug}")]
        public object Get(string slug) => null;

        [HttpPost]
        public object Create() => null;
    }
}
