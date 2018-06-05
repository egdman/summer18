from urllib import request, parse
from html.parser import HTMLParser
import asyncio
import aiohttp

class MyHTMLParser(HTMLParser):
  def __init__(self, root):
    super(MyHTMLParser, self).__init__()
    self.root = parse.urlsplit(root)
    self.foundLinks = []


  def handle_starttag(self, tag, attrs):
    # if tag == 'a':
    hrefs = (value for name, value in attrs if name == "href")
    link = next(hrefs, None)
    if link:
      url = parse.urlsplit(link)
      if url.netloc in ("", self.root.netloc):
        self.foundLinks.append(link)


def canDecode(data, enc):
  def _canDecode(chunk):
    try:
      chunk.decode(enc)
      return True
    except UnicodeDecodeError:
      return False

  sz = len(data)
  for chunkSz in range(sz, sz - 5, -1):
    if _canDecode(data[:chunkSz]): return True
  return False


def doDecode(data, enc):
  try:
    return data.decode(enc)
  except UnicodeDecodeError:
    return ""


def fetch(url):
  parser = MyHTMLParser(url)

  pageContent = ""
  with request.urlopen(url) as page:
    # print(page.url)
    # print(page.getcode())
    # print(page.info())

    header = page.info()
    try:
      contentSize = int(header["Content-Length"])
    except Exception:
      contentSize = 0

    print("size: {}".format(contentSize))

    firstChunk = page.read(1024)

    if canDecode(firstChunk, "utf-8"):
      # print("good utf-8")
      # print(firstChunk.decode("utf-8"))
      pageContent = firstChunk + page.read()
      pageContent = doDecode(pageContent, "utf-8")
    else:
      # print("not good utf-8")
      pass

  parser.feed(pageContent)
  # for lk in parser.foundLinks: print(lk)
  return pageContent, parser.foundLinks


async def _parseStream(stream):
  header = stream.headers
  try:
    contentSize = int(header["Content-Length"])
  except Exception:
    contentSize = 0

  print("size: {}".format(contentSize))

  firstChunk = await stream.content.read(1024)

  if canDecode(firstChunk, "utf-8"):
    # print("good utf-8")
    # print(firstChunk.decode("utf-8"))
    content = firstChunk + await stream.content.read()
    return doDecode(content, "utf-8")
  else:
    # print("not good utf-8")
    return ""


# async def fetchAsync(url, loop):
#   async with aiohttp.ClientSession(loop = loop) as session:
#     async with session.get(url) as page:
#       try:
#         pageContent = await _parseStream(page)
#       finally:
#         page.close()

#   parser = MyHTMLParser(url)
#   parser.feed(pageContent)
#   # print("found {} links".format(len(parser.foundLinks)))
#   # for lk in parser.foundLinks: print(lk)
#   return pageContent, parser.foundLinks


async def _safeDownloadContent(url, session):
  try:
    page = await session.get(url)

    try:
      return await _parseStream(page)
    finally:
      page.close()

  except Exception as ex:
    print(type(ex), ex)

  return ""


async def fetchAsync(url, loop):
  pageContent = ""
  async with aiohttp.ClientSession(loop = loop) as session:
    pageContent = await _safeDownloadContent(url, session)

  parser = MyHTMLParser(url)
  parser.feed(pageContent)
  # print("found {} links".format(len(parser.foundLinks)))
  # for lk in parser.foundLinks: print(lk)
  return pageContent, parser.foundLinks



urls = [
"https://docs.python.org/3/library/urllib.request.html#module-urllib.response",
"https://github.com/aio-libs/aiohttp/blob/master/aiohttp/streams.py",
"https://download.qt.io/official_releases/qt/5.11/5.11.0/qt-opensource-windows-x86-pdb-files-uwp-5.11.0.7z",
"https://bpy.wikipedia.org/wiki/%E0%A6%9C%E0%A6%BE%E0%A6%AA%E0%A6%BE%E0%A6%A8",
"https://stackoverflow.com/questions/9110593/asynchronous-requests-with-python-requests",
"https://www.youtube.com/watch?v=WiQYjPdq_qI",
"https://www.youtube.com/watch?v=FD_-b06JJtE",
"https://www.jytrhgf.com/watch?v=FD_-b06JJtE",
]


def main():
  loop = asyncio.get_event_loop()
  futures = list(asyncio.ensure_future(fetchAsync(url, loop)) for url in urls)
  loop.run_until_complete(asyncio.gather(*futures))

  print("=======")
  for f in futures:
    content, links = f.result()
    print(len(links), "links")

if __name__ == '__main__': main()
